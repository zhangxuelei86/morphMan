##   Copyright (c) Aslak W. Bergersen, Henrik A. Kjeldsberg. All rights reserved.
##   See LICENSE file for details.

##      This software is distributed WITHOUT ANY WARRANTY; without even
##      the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
##      PURPOSE.  See the above copyright notices for more information.

from scipy.signal import argrelextrema
from scipy.ndimage.filters import gaussian_filter

# Local import
from morphman.common import *


def get_maximum_coronal_coordinate(coronal_coordinate, length):
    value_index = coronal_coordinate[argrelextrema(coronal_coordinate, np.less_equal)[0]].min()
    max_coronal_coordinate_id = np.array(coronal_coordinate.tolist().index(value_index))
    if abs(length[max_coronal_coordinate_id] - length[-1]) > 30:
        print("-- Sanity check failed, checking for maximums")

        value_index = coronal_coordinate[argrelextrema(coronal_coordinate, np.greater_equal)[0]].max()
        max_coronal_coordinate_id = np.array(coronal_coordinate.tolist().index(value_index))
        if abs(length[max_coronal_coordinate_id] - length[-1]) > 30:
            print("-- Sanity check failed, no anterior bend in model. Exiting.")
            sys.exit(1)
    return max_coronal_coordinate_id


def get_centerline_coordinates(line, length):
    x = np.zeros(length.shape[0])
    y = np.zeros(length.shape[0])
    z = np.zeros(length.shape[0])
    for i in range(z.shape[0]):
        x[i] = line.GetPoints().GetPoint(i)[0]
        y[i] = line.GetPoints().GetPoint(i)[1]
        z[i] = line.GetPoints().GetPoint(i)[2]

    return {"x": x, "y": y, "z": z}


def orient_centerline(ica_centerline):
    """
    Check the orientation of the axial coordinate and
    reverse centerline if path of centerline is in distal direction.

    Args:
        ica_centerline (vtkPolyData): Centerline to check

    Returns:
        ica_centerline (vtkPolyData): Centerline, possibly reversed
    """
    length = get_curvilinear_coordinate(ica_centerline)
    coordinates = get_centerline_coordinates(ica_centerline, length)

    # Iterate through coordinates and find axial coordinate
    for _, coordinate in coordinates.items():
        coordinate = gaussian_filter(coordinate, 25)
        min_c = min(coordinate)
        max_c = max(coordinate)
        id0 = coordinate.tolist().index(min_c)
        id1 = coordinate.tolist().index(max_c)
        if id0 == 0 and id1 == (len(coordinate) - 1):
            return ica_centerline

        if id1 == 0 and id0 == (len(coordinate) - 1):
            return reverse_centerline(ica_centerline)

    return ica_centerline


def spline_centerline_and_compute_geometric_features(line, smooth, nknots):
    """
    Compute attributes and geometric parameters of input
    centerline, using B-splines (SciPy).

    Args:
        line (vtkPolyData): Centerline data.
        smooth (bool): Smooth centerline with VMTK if True.
        nknots (int): Number of knots for B-splines.

    Returns:
        line (vtkPolyData): Splined centerline.
    Returns:
        max_point_ids (ndarray): Array of max curvature values
    Returns:
        min_point_ids (ndarray): Array of min curvature values
    """
    data = np.zeros((line.GetNumberOfPoints(), 3))
    curv_coor = get_curvilinear_coordinate(line)

    # Collect data from centerline
    for i in range(data.shape[0]):
        data[i, :] = line.GetPoints().GetPoint(i)

    t = np.linspace(curv_coor[0], curv_coor[-1], nknots + 2)[1:-1]

    fx = splrep(curv_coor, data[:, 0], k=4, t=t)
    fy = splrep(curv_coor, data[:, 1], k=4, t=t)
    fz = splrep(curv_coor, data[:, 2], k=4, t=t)

    fx_ = splev(curv_coor, fx)
    fy_ = splev(curv_coor, fy)
    fz_ = splev(curv_coor, fz)

    data = np.zeros((len(curv_coor), 3))
    data[:, 0] = fx_
    data[:, 1] = fy_
    data[:, 2] = fz_

    header = ["X", "Y", "Z"]
    line = convert_numpy_data_to_polydata(data, header)

    # Let vmtk compute curve attributes
    line = vmtk_compute_centerline_attributes(line)
    line = vmtk_compute_geometric_features(line, smooth)

    # Compute curvature from the 'exact' spline to get a robust way of
    # finding max / min points on the centerline
    dlsfx = splev(curv_coor, fx, der=1)
    dlsfy = splev(curv_coor, fy, der=1)
    dlsfz = splev(curv_coor, fz, der=1)

    ddlsfx = splev(curv_coor, fx, der=2)
    ddlsfy = splev(curv_coor, fy, der=2)
    ddlsfz = splev(curv_coor, fz, der=2)

    c1xc2_1 = ddlsfz * dlsfy - ddlsfy * dlsfz
    c1xc2_2 = ddlsfx * dlsfz - ddlsfz * dlsfx
    c1xc2_3 = ddlsfy * dlsfx - ddlsfx * dlsfy

    curvature_ = np.sqrt(c1xc2_1 ** 2 + c1xc2_2 ** 2 + c1xc2_3 ** 2) / \
                 (dlsfx ** 2 + dlsfy ** 2 + dlsfz ** 2) ** 1.5

    max_point_ids = list(argrelextrema(curvature_, np.greater)[0])
    min_point_ids = list(argrelextrema(curvature_, np.less)[0])

    locator = get_vtk_point_locator(line)

    min_points = [[fx_[i], fy_[i], fz_[i]] for i in min_point_ids]
    max_points = [[fx_[i], fy_[i], fz_[i]] for i in max_point_ids]
    min_point_ids = []
    max_point_ids = []

    for point_min, point_max in zip(min_points, max_points):
        min_point_ids.append(locator.FindClosestPoint(point_min))
        max_point_ids.append(locator.FindClosestPoint(point_max))

    curvature = get_point_data_array("Curvature", line)
    line = get_k1k2_basis(curvature, line)

    length = get_curvilinear_coordinate(line)
    dddlsfx = splev(length, fx, der=3)
    dddlsfy = splev(length, fy, der=3)
    dddlsfz = splev(length, fz, der=3)

    torsion_spline = (dddlsfx * c1xc2_1 + dddlsfy * c1xc2_2 + dddlsfz * c1xc2_3) / \
                     (c1xc2_1 ** 2 + c1xc2_2 ** 2 + c1xc2_3 ** 2)
    torsion_array = create_vtk_array(torsion_spline, "Torsion")
    line.GetPointData().AddArray(torsion_array)

    curvature_ = np.sqrt(c1xc2_1 ** 2 + c1xc2_2 ** 2 + c1xc2_3 ** 2) / \
                 (dlsfx ** 2 + dlsfy ** 2 + dlsfz ** 2) ** 1.5
    curvature_[0] = curvature[0]
    curvature_[-1] = curvature[-1]

    curvature_array = create_vtk_array(curvature_, "Curvature")
    line.GetPointData().AddArray(curvature_array)

    return line, max_point_ids, min_point_ids


def map_landmarks(landmarks, centerline, algorithm):
    """
    Takes new landmarks and original centerline,
    mapping each landmark interface to the original centerline.
    Filters away duplicate landmarks

    Args:
        landmarks (dict): Contains landmarks.
        centerline (vtkPolyData): Original centerline.
        algorithm (str): Landmarking algorith, bogunovic or piccinelli

    Returns:
        mapped_landmarks (dict): Contains landmarks mapped to centerline.
    """
    mapped_landmarks = {}
    landmark_ids = []
    locator = get_vtk_point_locator(centerline)
    k = 1
    for key in landmarks:
        landmark = landmarks[key]
        landmark_id = locator.FindClosestPoint(landmark)

        if algorithm in ["kjeldsberg", "piccinelli"]:
            key = "C%s" if algorithm == "kjeldsberg" else "bend%s"
            if landmark_id in landmark_ids:
                continue  # Skip for duplicate landmarking point
            else:
                landmark_ids.append(landmark_id)
                landmark_mapped = centerline.GetPoint(landmark_id)
                mapped_landmarks[key % k] = landmark_mapped
                k += 1

        if algorithm == "bogunovic":
            landmark_mapped = centerline.GetPoint(landmark_id)
            landmarks[key] = landmark_mapped
            mapped_landmarks = landmarks

    return mapped_landmarks


def create_particles(base_path, algorithm, method):
    """
    Create a file with points where bends are located and
    remove points from manifest

    Args:
        base_path (str): Case location.
        algorithm (str): Name of landmarking algorithm.
        method (str): Method used for computing curvature.
    """

    info_filepath = base_path + "_info.json"
    filename_all_landmarks = base_path + "_landmark_%s_%s.particles" % (algorithm, method)
    print("Saving all landmarks to: %s" % filename_all_landmarks)

    output_all = open(filename_all_landmarks, "w")
    with open(info_filepath, ) as landmarks_json:
        landmarked_points = json.load(landmarks_json)

    for key in landmarked_points:
        if algorithm == "bogunovic":
            if key in ["ant_post", "post_inf", "inf_end", "sup_ant"]:
                p = landmarked_points[key]
                point = "%s %s %s" % (p[0], p[1], p[2])
                output_all.write(point + "\n")

        elif algorithm == "piccinelli":
            if key[0] == "b":
                p = landmarked_points[key]
                point = "%s %s %s" % (p[0], p[1], p[2])
                output_all.write(point + "\n")

        elif algorithm == "kjeldsberg":
            if key[0] == "C":
                p = landmarked_points[key]
                point = "%s %s %s" % (p[0], p[1], p[2])
                output_all.write(point + "\n")

    output_all.close()