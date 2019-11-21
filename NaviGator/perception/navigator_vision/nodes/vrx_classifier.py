#!/usr/bin/env python2
import rospy
import cv2
import numpy as np
from mil_ros_tools import Image_Subscriber, Image_Publisher, rosmsg_to_numpy
from mil_vision_tools import contour_mask, putText_ul, roi_enclosing_points, ImageMux, rect_from_roi
from collections import deque
from navigator_vision import VrxColorClassifier
import tf2_ros
from image_geometry import PinholeCameraModel
import sensor_msgs.point_cloud2
from sensor_msgs.msg import PointCloud2
from mil_msgs.msg import PerceptionObjectArray
from tf2_sensor_msgs.tf2_sensor_msgs import do_transform_cloud
from tf.transformations import quaternion_matrix
from mil_tools import thread_lock
from threading import Lock
from mil_msgs.srv import ObjectDBQuery, ObjectDBQueryRequest
from std_srvs.srv import SetBool
import pandas

lock = Lock()


def bbox_countour_from_rectangle(bbox):
    return np.array([[bbox[0][0], bbox[0][1]],
                     [bbox[1][0], bbox[0][1]],
                     [bbox[1][0], bbox[1][1]],
                     [bbox[0][0], bbox[1][1]]])


class VrxClassifier(object):
    def __init__(self):
        self.enabled = False
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.get_params()
        self.last_panel_points_msg = None
        self.database_client = rospy.ServiceProxy('/database/requests', ObjectDBQuery)
        self.sub = Image_Subscriber(self.image_topic, self.img_cb)
        self.camera_info = self.sub.wait_for_camera_info()
        self.camera_model = PinholeCameraModel()
        self.camera_model.fromCameraInfo(self.camera_info)
        if self.debug:
            self.image_mux = ImageMux(size=(self.camera_info.height, self.camera_info.width), shape=(1, 2),
                                      labels=['Result', 'Mask'])
            self.debug_pub = Image_Publisher('~debug_image')
        self.last_objects = None
        self.last_update_time = rospy.Time.now()
        self.objects_sub = rospy.Subscriber('/pcodar/objects', PerceptionObjectArray, self.process_objects, queue_size=2)
        self.enabled_srv = rospy.Service('~set_enabled', SetBool, self.set_enable_srv)
        if self.is_training:
            self.enabled = True

    @thread_lock(lock)
    def set_enable_srv(self, req):
        self.enabled = req.data
        return {'success': True}

    def in_frame(self, pixel):
        # TODO: < or <= ???
        return pixel[0] > 0 and pixel[0] < self.camera_info.width and pixel[1] > 0 and pixel[1] < self.camera_info.height

    @thread_lock(lock)
    def process_objects(self, msg):
        self.last_objects = msg

    def get_params(self):
        '''
        Set several constants used for image processing and classification
        from ROS params for runtime configurability.
        '''
        self.is_training = rospy.get_param('~train', False)
        self.debug = rospy.get_param('~debug', True)
        self.image_topic = rospy.get_param('~image_topic', '/camera/starboard/image_rect_color')
        self.update_period = rospy.Duration(1.0 / rospy.get_param('~update_hz', 1))
        self.classifier = VrxColorClassifier()
        self.classifier.train_from_csv()

    def get_box_roi(self, corners):
        roi = roi_enclosing_points(self.camera_model, corners, border=(-10, 0))
        if roi is None:
            rospy.logwarn('No points project into camera.')
            return None
        rect = rect_from_roi(roi)
        bbox_contour = bbox_countour_from_rectangle(rect)
        return bbox_contour

    def get_bbox(self, p, q_mat, obj_msg):
        points = np.zeros((len(obj_msg.points), 3) , dtype=np.float)
        for i in range(len(obj_msg.points)):
            points[i, :] = p + q_mat.dot(rosmsg_to_numpy(obj_msg.points[i]))
        return points

    def get_object_roi(self, p, q_mat, obj_msg):
        box_corners = self.get_bbox(p, q_mat, obj_msg)
        return self.get_box_roi(box_corners)

    @thread_lock(lock)
    def img_cb(self, img):
        if not self.enabled:
            return
        if self.camera_model is None:
            return
        if self.last_objects is None or len(self.last_objects.objects) == 0:
            return
        now = rospy.Time.now()
        if now - self.last_update_time < self.update_period:
            return
        self.last_update_time = now
        # Get Transform from ENU to optical at the time of this image
        transform = self.tf_buffer.lookup_transform(
            self.sub.last_image_header.frame_id,
            "enu",
            self.sub.last_image_header.stamp,
            timeout=rospy.Duration(1))
        translation = rosmsg_to_numpy(transform.transform.translation)
        rotation = rosmsg_to_numpy(transform.transform.rotation)
        rotation_mat = quaternion_matrix(rotation)[:3, :3]

        # Transform the center of each object into optical frame
        positions_camera = [translation + rotation_mat.dot(rosmsg_to_numpy(obj.pose.position))
                            for obj in self.last_objects.objects]
        pixel_centers = [self.camera_model.project3dToPixel(point) for point in positions_camera]
        distances = np.linalg.norm(positions_camera, axis=1)
        CUTOFF_METERS = 20

        # Get a list of indicies of objects who are sufficiently close and can be seen by camera
        met_criteria = []
        for i in xrange(len(self.last_objects.objects)):
            distance = distances[i]
            if self.in_frame(pixel_centers[i]) and distance < CUTOFF_METERS and positions_camera[i][2] > 0:
                met_criteria.append(i)
        # print 'Keeping {} of {}'.format(len(met_criteria), len(self.last_objects.objects))

        rois = [self.get_object_roi(translation, rotation_mat, self.last_objects.objects[i])
                  for i in met_criteria]
        debug = np.zeros(img.shape, dtype=img.dtype)

        if self.is_training:
            training = []

        for i in xrange(len(rois)):
            index = met_criteria[i]
            object_msg = self.last_objects.objects[index]
            object_id = object_msg.id
            if rois[i] is None:
                rospy.logwarn('Object {} had no points, skipping'.format(object_id))
                continue
            contour = np.array(rois[i], dtype=int)
            # Create image mask of just the object
            mask = contour_mask(contour, img_shape=img.shape)
            features = np.array(self.classifier.get_features(img, mask)).reshape(1, 9)
            class_probabilities = self.classifier.feature_probabilities(features)[0]
            most_likely_index = np.argmax(class_probabilities)
            most_likely_name = self.classifier.CLASSES[most_likely_index]
            probability = class_probabilities[most_likely_index]
            obj_title = object_msg.labeled_classification
            rospy.loginfo('Object {} {} classified as {} ({}%)'.format(object_id, object_msg.labeled_classification, most_likely_name, probability * 100.))
            if object_msg.labeled_classification != most_likely_name:
                cmd = '{}={}'.format(object_id, most_likely_name)
                rospy.loginfo('Updating object {} to {}'.format(object_id, most_likely_name))
                if not self.is_training:
                    self.database_client(ObjectDBQueryRequest(cmd=cmd))
            if self.is_training and obj_title != 'UNKNOWN':
                classification_index = self.classifier.CLASSES.index(obj_title)
                training.append(np.append(classification_index, features))

            # Draw debug info
            colorful = cv2.bitwise_or(img, img, mask=mask)
            debug = cv2.bitwise_or(debug, colorful)
            scale = 3
            thickness = 2
            center = np.array(pixel_centers[index], dtype=int)
            text = str(object_id)
            putText_ul(debug, text, center, fontScale=scale, thickness=thickness)

        if self.is_training and len(training) != 0:
           training = np.array(training)
           try:
               previous_data = pandas.DataFrame.from_csv(self.classifier.training_file).values
               data = np.vstack((previous_data, training))
           except Exception as e:
               data = training
           self.classifier.save_csv(data[:, 1:], data[:, 0])
           rospy.signal_shutdown('fdfd')
           raise Exception('did something, kev')

        self.image_mux[0] = img
        self.image_mux[1] = debug 
        self.debug_pub.publish(self.image_mux())
        return


if __name__ == '__main__':
    rospy.init_node('vrx_classifier')
    c = VrxClassifier()
    rospy.spin()