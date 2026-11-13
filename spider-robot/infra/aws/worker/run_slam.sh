#!/usr/bin/env bash
# Inside the container: replay the bag through Point-LIO and keep the accumulated map.
set -eo pipefail
JOB="$1"
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash
roslaunch point_lio_unilidar mapping_unilidar_l2.launch rviz:=false &
LAUNCH=$!
sleep 5
rosbag play --clock -r 1.0 "/data/$JOB.bag"
sleep 5
kill -INT "$LAUNCH"
wait "$LAUNCH" || true
cp /catkin_ws/src/point_lio_unilidar/PCD/scans.pcd "/data/$JOB.pcd"
