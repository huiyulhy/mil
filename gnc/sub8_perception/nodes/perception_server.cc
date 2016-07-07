#include <sub8_vision_lib/object_finder.hpp>

///////////////////////////////////////////////////////////////////////////////////////////////////
// Main ///////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////////////////////////////////////////////////////////////////////

int main(int argc, char **argv) {
  ros::init(argc, argv, "torpedo_board_perception");
  ROS_INFO("Initializing node /torpedo_board_perception");
  Sub8TorpedoBoardDetector torpedo_board_detector;
  ros::spin();
}
