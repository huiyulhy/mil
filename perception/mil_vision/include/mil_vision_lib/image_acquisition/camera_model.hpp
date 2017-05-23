#pragma once

#include <ros/ros.h>
#include <Eigen/Core>

namespace mil_vision
{
template <typename T = float>
class CameraModel
{
public:
  ///////////////////////////////////////////////////////////////////////////////////////////////
  // Constructors and Destructors ///////////////////////////////////////////////////////////////
  ///////////////////////////////////////////////////////////////////////////////////////////////

  CameraModel()
  {
  }

  ~CameraModel()
  {
  }

private:
  ///////////////////////////////////////////////////////////////////////////////////////////////
  // Private Methods ////////////////////////////////////////////////////////////////////////////
  ///////////////////////////////////////////////////////////////////////////////////////////////
  Eigen::Matrix<T, 3, 4> get_projection_matrix();

  ///////////////////////////////////////////////////////////////////////////////////////////////
  // Private Members ////////////////////////////////////////////////////////////////////////////
  ///////////////////////////////////////////////////////////////////////////////////////////////

  int ROWS = 0;
  int COLS = 0;

  // Distortion model (only the plum-bob model is currently supported)
  T D[5] = { 0, 0, 0, 0, 0 };

  // Camera Geometry
  Eigen::Matrix<T, 3, 3> K;  // Camera intrinsics
  Eigen::Matrix<T, 3, 3> C;  // Center of projection in world frame
  Eigen::Matrix<T, 3, 3> R;  // Orientation of camera frame relative to world frame
};

template <typename T>
Eigen::Matrix<T, 3, 4> CameraModel<T>::get_projection_matrix()
{
  Eigen::Matrix<T, 3, 1> v;
  Eigen::DiagonalMatrix<T, 3> I = v.asDiagonal();
  Eigen::Matrix<T, 3, 4> aug;
  aug.block(0, 0, 2, 2) = I;
  aug.col(2) = C;
  return K * R * aug;
}

}  // namespace mil_vision