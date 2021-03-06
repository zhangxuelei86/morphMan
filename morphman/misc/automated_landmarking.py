##   Copyright (c) Aslak W. Bergersen, Henrik A. Kjeldsberg. All rights reserved.
##   See LICENSE file for details.

##      This software is distributed WITHOUT ANY WARRANTY; without even
##      the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
##      PURPOSE.  See the above copyright notices for more information.

import os
from argparse import ArgumentParser, RawDescriptionHelpFormatter

from scipy.ndimage.filters import gaussian_filter
from scipy.signal import argrelextrema

# Local import
from morphman.common import *
from scipy.ndimage.filters import gaussian_filter


def automated_landmarking(input_filepath, approximation_method, resampling_step, algorithm, nknots, smooth_line,
                          smoothing_factor_curv, smoothing_factor_torsion, iterations, coronal_axis):
    """
    Compute carotid siphon and perform landmarking.

    Args:
        input_filepath (str): Location of case to landmark.
        approximation_method (str): Method used for computing curvature and torsion.
        resampling_step (float): Resampling step. Is None if no resampling.
        algorithm (str): Name of landmarking algorithm.
        nknots (int): Number of knots for B-splines.
        smooth_line (bool): Smooths centerline with VMTK if True.
        smoothing_factor_curv (float): Smoothing factor used in VMTK for curvature
        smoothing_factor_torsion (float): Smoothing factor used in VMTK for torsion
        iterations (int): Number of smoothing iterations.
        coronal_axis (str) : Axis determining coronal coordinate
    """
    base_path = get_path_names(input_filepath)

    # Extract carotid siphon
    ica_centerline = extract_ica_centerline(base_path, input_filepath, resampling_step)

    # Check axial coordinate of centerline, reverse if needed
    ica_centerline = orient_centerline(ica_centerline)

    # Landmark
    if algorithm == "bogunovic":
        landmarking_bogunovic(ica_centerline, base_path, approximation_method, algorithm, resampling_step, smooth_line,
                              nknots, smoothing_factor_curv, iterations, coronal_axis)
    elif algorithm == "piccinelli":
        landmarking_piccinelli(ica_centerline, base_path, approximation_method, algorithm, resampling_step, smooth_line,
                               nknots, smoothing_factor_curv, smoothing_factor_torsion, iterations)


def landmarking_bogunovic(centerline, base_path, approximation_method, algorithm, resampling_step, smooth_line, nknots,
                          smoothing_factor, iterations, coronal_axis):
    """
    Perform landmarking of an input centerline to
    identify different segments along the vessel.
    Landmarking algorithm based on Bogunovic (2012).
    Bends are identified where the angle in the k1-k2 basis
    exceeds a certain limit.

    Args:
        centerline (vtkPolyData): Centerline data points.
        base_path (str): Location of case to landmark.
        approximation_method (str): Method used for computing curvature.
        algorithm (str): Name of landmarking algorithm.
        resampling_step (float): Resampling step. Is None if no resampling.
        smooth_line (bool): Smooths centerline with VMTK if True.
        nknots (int): Number of knots for B-splines.
        smoothing_factor (float): Smoothing factor used in VMTK
        iterations (int): Number of smoothing iterations.
        coronal_axis (str) : Axis determining coronal coordinate

    Returns:
        landmarks (dict): Landmarking interfaces as points.
    """

    if resampling_step is not None:
        centerline = vmtk_resample_centerline(centerline, length=resampling_step)

    if approximation_method == "vmtk":
        line = vmtk_compute_centerline_attributes(centerline)
        line = vmtk_compute_geometric_features(line, smooth_line, factor=smoothing_factor, iterations=iterations)
        curvature = get_point_data_array("Curvature", line)
        curvature = gaussian_filter(curvature, 2)

    elif approximation_method == "disc":
        neigh = 20
        line = vmtk_compute_centerline_attributes(centerline)
        line = vmtk_compute_geometric_features(line, smooth_line, factor=smoothing_factor, iterations=iterations)
        line, curvature__ = compute_discrete_derivatives(line, neigh=neigh)
        curvature = []
        for c in curvature__:
            curvature.append([c])
        curvature = np.array(curvature)

    elif approximation_method == "spline":
        line, max_point_ids, min_point_ids = spline_centerline_and_compute_geometric_features(centerline, smooth_line,
                                                                                              nknots)
        curvature = get_point_data_array("Curvature", line)

    if approximation_method != "spline":
        max_point_ids = list(argrelextrema(curvature, np.greater)[0])
        min_point_ids = list(argrelextrema(curvature, np.less)[0])
        get_k1k2_basis(curvature, line)

    length = get_curvilinear_coordinate(line)
    k1 = get_point_data_array("k1", line)
    k2 = get_point_data_array("k2", line)

    # Remove a min / max point that is in reality a saddle point
    for i in min_point_ids:
        for j in max_point_ids:
            if abs(i - j) < 5 and abs(curvature[i] - curvature[j]) < 0.01:
                if i in min_point_ids:
                    min_point_ids.remove(i)
                if j in max_point_ids:
                    max_point_ids.remove(j)

    k1_points = k1[max_point_ids]
    k2_points = k2[max_point_ids]
    k_points = np.zeros((k1_points.shape[0], 2))
    k_points[:, 0] = k1_points[:, 0]
    k_points[:, 1] = k2_points[:, 0]
    theta = np.zeros(k1_points.shape[0] - 1)
    for i in range(theta.shape[0]):
        a = k_points[i, :] / np.sqrt(np.sum(k_points[i, :] ** 2))
        b = k_points[i + 1, :] / np.sqrt(np.sum(k_points[i + 1, :] ** 2))
        theta[i] = math.acos(np.dot(a, b))
        theta[i] = theta[i] * 180 / math.pi

    # Tolerance parameters from Bogunovic et al. (2012)
    tol_ant_post = 60
    tol_sup_ant = 45
    tol_post_inf = 45
    tol_inf_end = 110

    # Find coronal coordinate and maximum (within anterior bend)
    coordinates = get_centerline_coordinates(line, length)
    coronal_coordinate = coordinates[coronal_axis]
    max_coronal_coordinate_id = get_maximum_coronal_coordinate(coronal_coordinate, length)

    def find_interface(start, direction, tol, part):
        stop = direction if direction == -1 else theta.shape[0]
        success = False
        for i in range(start - 1, stop, direction):
            if theta[i] > tol:
                success = True
                break

        if success:
            start = max_point_ids[i]
            stop = max_point_ids[i + 1]
            index = ((min_point_ids > start) * (min_point_ids < stop)).nonzero()[0].max()
            min_point = (min_point_ids[index])
            interfaces[part] = min_point

        elif not success and part == "sup_ant":
            print("-- Where not able to identify the interface between the " +
                  "anterior and superior bend. Check the coronal coordinates")
            return None

        elif not success and part != "inf_end":
            print("-- The geometry is to short to be classified with superior" +
                  ", anterior, posterior and inferior.")
            return None

        elif not success and part == "inf_end":
            interfaces["inf_end"] = np.array([0])
            i = 0
            print("-- End of inferior is at the end of the geometry, this might" +
                  "affect the geometry stats")
        else:
            print("-- Something happened, idea: some bend ended at the last point")
            return None

        return i

    interfaces = {}
    min_point_ids = np.array(min_point_ids)

    index = np.array((max_coronal_coordinate_id > max_point_ids).nonzero()[0]).max()
    start = find_interface(index, -1, tol_ant_post, "ant_post")
    if start is None:
        return None
    start = find_interface(start, -1, tol_post_inf, "post_inf")
    if start is None:
        return None
    find_interface(start, -1, tol_inf_end, "inf_end")
    start = find_interface(index + 1, 1, tol_sup_ant, "sup_ant")
    if start is None:
        return None

    # Set landmarks following Bogunovic
    landmarks = {}
    for k, v in interfaces.items():
        landmarks[k] = line.GetPoint(int(v))

    # Map landmarks to initial centerline
    landmarks = map_landmarks(landmarks, centerline, algorithm)

    # Save landmarks
    print("-- Case was successfully landmarked.")
    if landmarks is not None:
        write_parameters(landmarks, base_path)
        create_particles(base_path, algorithm, approximation_method)

    return landmarks


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


def landmarking_piccinelli(centerline, base_path, approximation_method, algorithm, resampling_step,
                           smooth_line, nknots, smoothing_factor_curv, smoothing_factor_torsion,
                           iterations):
    """
    Perform landmarking of an input centerline to
    identify different segments along the vessel.
    Landmarking algorithm based on Bogunovic et al. (2012).
    Uses curvature and torsion to objectively subdivide
    the siphon into bends.
    Subdivision of individual siphon bends is
    performed by identifying locations of curvature and torsion peaks along
    the siphon and defining a bend for each curvature peak delimited by 2
    enclosing (proximal and distal) torsion peaks.

    Args:
        centerline (vtkPolyData): Centerline data points.
        base_path (str): Location of case to landmark.
        approximation_method (str): Method used for computing curvature.
        algorithm (str): Name of landmarking algorithm.
        resampling_step (float): Resampling step. Is None if no resampling.
        smooth_line (bool): Smooths centerline with VMTK if True.
        nknots (int): Number of knots for B-splines.
        smoothing_factor_curv (float): Smoothing factor for computing curvature.
        smoothing_factor_torsion (float): Smoothing factor for computing torsion.
        iterations (int): Number of smoothing iterations.

    Returns:
        landmarks (dict): Landmarking interfaces as points.
    """

    if resampling_step is not None:
        centerline = vmtk_resample_centerline(centerline, resampling_step)

    if approximation_method == "spline":
        line, max_point_ids, _ = spline_centerline_and_compute_geometric_features(centerline, smooth_line, nknots)

        # Get curvature and torsion, find peaks
        curvature = get_point_data_array("Curvature", line)
        torsion = get_point_data_array("Torsion", line)
        torsion_smooth = gaussian_filter(torsion, 10)
        max_point_tor_ids = list(argrelextrema(abs(torsion_smooth), np.greater)[0])

    elif approximation_method == "vmtk":
        line = centerline
        line_curv = vmtk_compute_geometric_features(centerline, True, outputsmoothed=False,
                                                    factor=smoothing_factor_curv, iterations=iterations)
        line_tor = vmtk_compute_geometric_features(centerline, True, outputsmoothed=False,
                                                   factor=smoothing_factor_torsion, iterations=iterations)
        # Get curvature and torsion, find peaks
        curvature = get_point_data_array("Curvature", line_curv)
        torsion = get_point_data_array("Torsion", line_tor)

        # Smooth torsion curve to remove noise
        torsion_smooth = gaussian_filter(torsion, 25)
        max_point_ids = list(argrelextrema(curvature, np.greater)[0])
        max_point_tor_ids = list(argrelextrema(abs(torsion_smooth), np.greater)[0])

    else:
        raise ValueError("ERROR: Selected method for computing curvature / torsion not available" +
                         "\nPlease select between 'spline' and 'vmtk'")

    # Extract local curvature minimums
    length = get_curvilinear_coordinate(line)

    # Remove points too close to the ends of the siphon
    for i in max_point_ids:
        if length[i] in length[-10:] or length[i] in length[:10]:
            max_point_ids.remove(i)

    # Remove curvature and torsion peaks too close to each other
    tolerance = 70
    dist = []
    dist_tor = []
    for i in range(len(max_point_ids) - 1):
        dist.append(max_point_ids[i + 1] - max_point_ids[i])
    for i in range(len(max_point_tor_ids) - 1):
        dist_tor.append(max_point_tor_ids[i + 1] - max_point_tor_ids[i])

    curv_remove_ids = []
    for i, dx in enumerate(dist):
        if dx < tolerance:
            curv1 = curvature[max_point_ids[i]]
            curv2 = curvature[max_point_ids[i + 1]]
            if curv1 > curv2:
                curv_remove_ids.append(max_point_ids[i + 1])
            else:
                curv_remove_ids.append(max_point_ids[i])

    tor_remove_ids = []
    for i, dx in enumerate(dist_tor):
        if dx < tolerance:
            tor1 = torsion_smooth[max_point_tor_ids[i]]
            tor2 = torsion_smooth[max_point_tor_ids[i + 1]]
            if tor1 > tor2:
                tor_remove_ids.append(max_point_tor_ids[i + 1])
            else:
                tor_remove_ids.append(max_point_tor_ids[i])

    max_point_ids = [ID for ID in max_point_ids if ID not in curv_remove_ids]
    max_point_tor_ids = [ID for ID in max_point_tor_ids if ID not in tor_remove_ids]

    # Define bend interfaces based on Piccinelli et al.
    def find_interface():
        found = False
        interface = {}
        k = 0
        start_id = 0
        for c in max_point_ids:
            for i in range(start_id, len(max_point_tor_ids) - 1):
                if max_point_tor_ids[i] < c < max_point_tor_ids[i + 1] and not found:
                    interface["bend%s" % (k + 1)] = np.array([max_point_tor_ids[i]])
                    k += 1
                    interface["bend%s" % (k + 1)] = np.array([max_point_tor_ids[i + 1]])
                    k += 1
                    start_id = i + 1
                    found = True
            found = False

        return interface

    # Compute and extract interface points
    interfaces = find_interface()
    landmarks = {}
    for k, v in interfaces.items():
        landmarks[k] = line.GetPoints().GetPoint(int(v))

    # Map landmarks to initial centerline
    landmarks = map_landmarks(landmarks, centerline, algorithm)
    print("Number of landmarks (Segments): %s" % len(landmarks))

    # Save landmarks
    print("-- Case was successfully landmarked.")
    try:
        os.remove(base_path + "_info.json")
        os.remove(base_path + "_landmark_piccinelli_vmtk.particles")
    except:
        pass
    if landmarks is not None:
        write_parameters(landmarks, base_path)
        create_particles(base_path, algorithm, approximation_method)

    return landmarks


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
        coordinate = gaussian_filter(coordinate, 100)
        min_c = min(coordinate)
        max_c = max(coordinate)
        id0 = coordinate.tolist().index(min_c)
        id1 = coordinate.tolist().index(max_c)
        if id0 == 0 and id1 == (len(coordinate) - 1):
            return ica_centerline

        if id1 == 0 and id0 == (len(coordinate) - 1):
            return reverse_centerline(ica_centerline)


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

        if algorithm == "piccinelli":
            if landmark_id in landmark_ids:
                continue  # Skip for duplicate landmarking point
            else:
                landmark_ids.append(landmark_id)
                landmark_mapped = centerline.GetPoint(landmark_id)
                mapped_landmarks["bend%s" % k] = landmark_mapped
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
            p = landmarked_points[key]
            point = "%s %s %s" % (p[0], p[1], p[2])
            output_all.write(point + "\n")

    output_all.close()


def read_command_line():
    """
    Read arguments from commandline
    """
    description = "Perform landmarking of an input centerline to" + \
                  "identify different segments along the vessel." + \
                  "Landmarking algorithm based on Bogunovic et al. (2012) " + \
                  " and Piccinelli et al. (2011)."

    parser = ArgumentParser(description=description, formatter_class=RawDescriptionHelpFormatter)

    # Required arguments
    required = parser.add_argument_group('Required arguments')
    required.add_argument('-i', '--ifile', type=str, default=None, required=True,
                          help="Path to the surface model")

    # Optional arguments
    parser.add_argument('-m', '--approximation-method', type=str, default="vmtk",
                        help="Choose which method used for computing curvature and torsion. Default is 'vmtk'.",
                        choices=['spline', 'vmtk', 'disc'])
    parser.add_argument('-a', '--algorithm', type=str, default="bogunovic",
                        help="Choose which landmarking algorithm to use: " +
                             "'bogunovic' or 'piccinelli'. Default is 'bogunovic'.",
                        choices=['bogunovic', 'piccinelli'])
    parser.add_argument('-ca', '--coronal-axis', type=str, default="z",
                        help="Axis describing coronal coordinate. Default is 'z'.",
                        choices=['x', 'y', 'z'])
    parser.add_argument('-k', '--nknots', type=int, default=11,
                        help="Number of knots used in B-splines.")
    parser.add_argument('-sl', '--smooth-line', type=str2bool, default=False,
                        help="If the original centerline should be smoothed " +
                             "when computing the centerline attributes")
    parser.add_argument('-facc', '--smoothing-factor-curvature', type=float, default=1.5,
                        help="Smoothing factor for computing curvature.")
    parser.add_argument('-fact', '--smoothing-factor-torsion', type=float, default=1.2,
                        help="Smoothing factor for computing torsion.")
    parser.add_argument('-it', '--iterations', type=int, default=100,
                        help="Smoothing iterations.")
    parser.add_argument("-r", "--resampling-step", type=float, default=0.1,
                        help="Resampling step in centerlines.")
    args = parser.parse_args()

    return dict(input_filepath=args.ifile, approximation_method=args.approximation_method,
                coronal_axis=args.coronal_axis, resampling_step=args.resampling_step, algorithm=args.algorithm,
                nknots=args.nknots, smooth_line=args.smooth_line, smoothing_factor_curv=args.smoothing_factor_curvature,
                smoothing_factor_torsion=args.smoothing_factor_torsion, iterations=args.iterations)


if __name__ == '__main__':
    automated_landmarking(**read_command_line())
