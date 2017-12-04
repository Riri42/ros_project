#!/usr/bin/env python

import rospy
import message_filters
import tf
import struct
from laser_assembler.srv import AssembleScans
from laser_geometry import LaserProjection
from sensor_msgs.msg import PointCloud, ChannelFloat32, Image, CameraInfo, LaserScan
from sensor_msgs import point_cloud2
from image_geometry import PinholeCameraModel
from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import PointStamped, Point32

rospy.init_node('camera_lidar')

tf_listener = tf.TransformListener()

image_sub = message_filters.Subscriber('camera/image_raw', Image)
image_cache = message_filters.Cache(image_sub, 10)

camera_model = PinholeCameraModel()
bridge = CvBridge()

def on_camera_info(camera_info):
    camera_model.fromCameraInfo(camera_info)

camera_info_sub = rospy.Subscriber('camera/camera_info', CameraInfo, on_camera_info, queue_size=1)

laser_projector = LaserProjection()

point_cloud_pub = rospy.Publisher('cloud', PointCloud, queue_size=1)

def on_scan(scan):

    image = image_cache.getElemBeforeTime(scan.header.stamp)

    if not image:
        return

    try:
        cv_image = bridge.imgmsg_to_cv2(image, desired_encoding="rgb8")
        height, width = cv_image.shape[:2]
    except CvBridgeError as e:
        rospy.logerr('Cannot convert image to OpenCV: ' + str(e))
        return

    point_cloud = laser_projector.projectLaser(scan, channel_options=LaserProjection.ChannelOption.TIMESTAMP)

    color_channel = ChannelFloat32()
    color_channel.name = 'rgb'
    points = []

    try:
        tf_listener.waitForTransform(image.header.frame_id, scan.header.frame_id, scan.header.stamp, rospy.Duration(1.0))
    except tf.Exception as e:
        rospy.logwarn('Cannot transform scan: ' + str(e))
        return

    for point in point_cloud2.read_points(point_cloud, field_names = ("x", "y", "z"), skip_nans=True):

        point_stamped = PointStamped()
        point_stamped.header = scan.header
        point_stamped.point.x = point[0]
        point_stamped.point.y = point[1]
        point_stamped.point.z = point[2]

        try:
            transformed_point = tf_listener.transformPoint(image.header.frame_id, point_stamped)
        except tf.Exception as e:
            rospy.logwarn('Cannot transform scan point: ' + str(e))
            return

        point_3d = (transformed_point.point.z, transformed_point.point.y, -transformed_point.point.x)
        u, v = camera_model.project3dToPixel(point_3d)
        u = int(round(u))
        v = int(round(v))

        if u < 0 or u >= height or v < 0 or v >= width:
            continue
        else:
            color = cv_image[u, v]

        rgb8 = struct.pack('BBBB', color[2], color[1], color[0], 0)
        rgb_float32 = struct.unpack('f', rgb8)[0]
        color_channel.values.append(rgb_float32)

        point_32 = Point32()
        point_32.x = transformed_point.point.x
        point_32.y = transformed_point.point.y
        point_32.z = transformed_point.point.z
        points.append(point_32)

    rgb_point_cloud = PointCloud()
    rgb_point_cloud.header.frame_id = image.header.frame_id
    rgb_point_cloud.header.stamp = scan.header.stamp
    rgb_point_cloud.channels = [color_channel]
    rgb_point_cloud.points = points

    point_cloud_pub.publish(rgb_point_cloud)

scan_sub = rospy.Subscriber('scan', LaserScan, on_scan, queue_size=1)

rospy.spin()
