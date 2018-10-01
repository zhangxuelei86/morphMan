from argparse import ArgumentParser, RawDescriptionHelpFormatter
from os import path

# Local import
from common import *


def rotate_branches(input_filepath, output_filepath, smooth, smooth_factor, angle,
                    keep_fixed_1, keep_fixed_2, bif, lower, no_smooth, no_smooth_point,
                    poly_ball_size, cylinder_factor, resampling_step,
                    version, region_of_interest, region_points):
    """
    Objective rotation of daughter branches, by rotating
    centerlines and Voronoi diagram about the bifuraction center.
    The implementation is an extension of the original method
    presented by Ford et al. (2009), for aneurysm removal,
    which introduces the possibility to rotate the
    daughter branches a given angle.
    Includes the option to rotate only one of the daughter branches.

    Args:
        input_filepath (str): Path to input surface.
        smooth (bool): Determine if the voronoi diagram should be smoothed.
        smooth_factor (float): Smoothing factor used for voronoi diagram smoothing.
        angle (float): Angle which daughter branches are moved, in radians.
        keep_fixed_1 (bool): Leaves first branch untouched if True.
        keep_fixed_2 (bool): Leaves second branch untouched if True.
        bif (bool): Interpolates bifurcation is True.
        lower (bool): Interpolates a lowered line through the bifurcation if True.
        cylinder_factor(float): Factor for choosing the smaller cylinder during Voronoi interpolation.
        resampling_step (float): Resampling step used to resample centerlines.
        version (bool): Determines bifurcation interpolation method.
    """
    # Filenames
    base_path = get_path_names(input_filepath)

    # Output filepaths
    # Centerliens
    centerline_par_path = base_path + "_centerline_par.vtp"
    centerline_bif_path = base_path + "_centerline_bif.vtp"
    centerline_clipped_path = base_path + "_centerline_clipped_ang.vtp"
    centerline_clipped_bif_path = base_path + "_centerline_clipped_bif_ang.vtp"
    centerline_new_path = base_path + "_centerline_interpolated_ang.vtp"
    centerline_new_bif_path = base_path + "_centerline_interpolated_bif_ang.vtp"
    centerline_new_bif_lower_path = base_path + "_centerline_interpolated_bif_lower_ang.vtp"
    centerline_relevant_outlets_path = base_path + "_centerline_relevant_outlets.vtp"
    centerline_rotated_path = base_path + "_centerline_rotated_ang.vtp"
    centerline_rotated_bif_path = base_path + "_centerline_rotated_bif_ang.vtp"
    centerline_bif_clipped_path = base_path + "_centerline_clipped_out.vtp"

    # Voronoi diagrams
    voronoi_clipped_path = base_path + "_voronoi_clipped_ang.vtp"
    voronoi_ang_path = base_path + "_voronoi_ang.vtp"
    voronoi_rotated_path = base_path + "_voronoi_rotated_ang.vtp"

    # Points
    points_clipp_path = base_path + "_clippingpoints.vtp"
    points_div_path = base_path + "_divergingpoints.vtp"

    # Clean and capp / uncapp surface
    surface, capped_surface = prepare_surface(base_path, input_filepath)

    # Get inlet and outlets
    inlet, outlets = get_centers(surface, base_path)
    if region_of_interest == "manuall":
        outlet1, outlet2 = get_relevant_outlets(capped_surface, base_path)
    else:
        outlet1, outlet2 = region_points[:3], region_points[3:]

    # Sort outlets
    outlets, outlet1, outlet2 = sort_outlets(outlets, outlet1, outlet2, base_path)

    # Compute parent artery and aneurysm centerline
    centerline_par, voronoi, pole_ids = compute_centerlines(inlet, outlets,
                                                            centerline_par_path,
                                                            capped_surface,
                                                            resampling=resampling_step,
                                                            base_path=base_path)

    # Additional centerline for bifurcation
    centerline_relevant_outlets, _, _ = compute_centerlines(inlet, outlet1 + outlet2,
                                                            centerline_relevant_outlets_path,
                                                            capped_surface,
                                                            resampling=resampling_step,
                                                            voronoi=voronoi,
                                                            pole_ids=pole_ids,
                                                            base_path=base_path)
    centerline_bif, _, _ = compute_centerlines(outlet1, outlet2, centerline_bif_path,
                                               capped_surface, resampling=resampling_step,
                                               voronoi=voronoi, pole_ids=pole_ids)

    # Create a tolerance for diverging
    tolerance = get_tolerance(centerline_par)

    # Get data from centerlines and rotation matrix
    data = get_data(centerline_relevant_outlets, centerline_bif, tolerance)
    R, m = rotation_matrix(data, angle, keep_fixed_1, keep_fixed_2)
    write_parameters(data, base_path)

    # Compute and smooth voornoi diagram (not aneurysm)
    print("-- Compute voronoi diagram.")
    if smooth:
        voronoi = prepare_voronoi_diagram(capped_surface, centerline_par, base_path, smooth,
                                          smooth_factor, no_smooth, no_smooth_point,
                                          voronoi, pole_ids)

    # Locate divpoints and endpoints, for bif or lower, rotated or not
    key = "div_point"
    div_points = get_points(data, key, R, m, rotated=False, bif=False)
    div_points_rotated = get_points(data, key, R, m, rotated=True, bif=False)
    div_points_rotated_bif = get_points(data, key, R, m, rotated=True, bif=True)

    key = "end_point"
    end_points = get_points(data, key, R, m, rotated=False, bif=False)
    end_points_rotated = get_points(data, key, R, m, rotated=True, bif=False)
    end_points_bif = get_points(data, key, R, m, rotated=False, bif=True)
    end_points_rotated_bif = get_points(data, key, R, m, rotated=True, bif=True)

    write_points(div_points[0], points_div_path)
    write_points(end_points[0], points_clipp_path)

    # Clip centerlines
    print("-- Clipping centerlines.")
    patch_cl = create_parent_artery_patches(centerline_par, end_points[0])
    write_polydata(patch_cl, centerline_clipped_path)

    # Get the centerline which was clipped away
    clipped_centerline = get_clipped_centerline(centerline_relevant_outlets, data)
    write_polydata(clipped_centerline, centerline_bif_clipped_path)

    if lower or bif:
        patch_bif_cl = create_parent_artery_patches(centerline_bif, end_points_bif[0])
        write_polydata(patch_bif_cl, centerline_clipped_bif_path)

    # Clip the voronoi diagram
    print("-- Clipping the Voronoi diagram")
    if path.exists(voronoi_clipped_path):
        voronoi_clipped = read_polydata(voronoi_clipped_path)
    else:
        voronoi_clipped, _ = split_voronoi_with_centerlines(voronoi, patch_cl, clipped_centerline)
        write_polydata(voronoi_clipped, voronoi_clipped_path)

    # Rotate branches (Centerline and Voronoi diagram)
    print("-- Rotate centerlines and voronoi diagram.")
    rotated_cl = rotate_cl(patch_cl, end_points[1], m, R)
    write_polydata(rotated_cl, centerline_rotated_path)

    if lower or bif:
        rotated_bif_cl = rotate_cl(patch_bif_cl, end_points_bif[1], m, R)
        write_polydata(rotated_bif_cl, centerline_rotated_bif_path)

    rotated_voronoi = rotate_voronoi(voronoi_clipped, patch_cl, end_points[1], m, R)
    write_polydata(rotated_voronoi, voronoi_rotated_path)

    # Interpolate the centerline
    print("-- Interpolate centerlines.")
    interpolated_cl = interpolate_patch_centerlines(rotated_cl, centerline_par,
                                                  div_points_rotated[0].GetPoint(0),
                                                  None, False)
    write_polydata(interpolated_cl, centerline_new_path.replace(".vtp", "1.vtp"))

    if bif:
        interpolated_bif = interpolate_patch_centerlines(rotated_bif_cl, centerline_bif,
                                                       None, "bif", True)
        write_polydata(interpolated_bif, centerline_new_bif_path)

    if lower:
        center = ((1 / 9.) * div_points[1][0] + (4 / 9.) * div_points[1][1] + \
                  (4 / 9.) * div_points[1][2]).tolist()
        div_points_rotated_bif[0].SetPoint(0, center[0], center[1], center[2])
        interpolated_bif_lower = interpolate_patch_centerlines(rotated_bif_cl, centerline_bif,
                                                             div_points_rotated_bif[0].GetPoint(0),
                                                             "lower", True)
        write_polydata(interpolated_bif_lower, centerline_new_bif_lower_path)

    interpolated_cl = merge_cl(interpolated_cl, div_points_rotated[1],
                               end_points_rotated[1])
    write_polydata(interpolated_cl, centerline_new_path)

    bif_ = []
    if lower and bif:
        bif_ = [interpolated_bif, interpolated_bif_lower, rotated_bif_cl]
    elif bif:
        bif_ = [interpolated_bif, rotated_bif_cl]
    elif lower:
        bif_ = [interpolated_bif_lower, rotated_bif_cl]

    # Interpolate voronoi diagram
    print("-- Interpolate voronoi diagram.")
    interpolated_voronoi = interpolate_voronoi_diagram(interpolated_cl, rotated_cl,
                                                       rotated_voronoi,
                                                       end_points_rotated,
                                                       bif_, cylinder_factor)

    # Note: This function is slow, and can be commented, but at the cost of robustness.
    #interpolated_voronoi = remove_distant_points(interpolated_voronoi, interpolated_cl)
    write_polydata(interpolated_voronoi, voronoi_ang_path)

    # Write a new surface from the new voronoi diagram
    print("-- Create new surface.")
    new_surface = create_new_surface(interpolated_voronoi, poly_ball_size)

    print("-- Preparing surface for output.")
    new_surface = prepare_surface_output(new_surface, surface, interpolated_cl,
                                         output_filepath, test_merge=True, changed=True,
                                         old_centerline=centerline_par)

    print("-- Writing new surface to {}.".format(output_filepath))
    write_polydata(new_surface, output_filepath)


def get_points(data, key, R, m, rotated=True, bif=False):
    """
    Finds spesific points around the bifurcation, based on the
    key argument. Points can before or after rotation.

    Args:
        data (dict): Contains information about points and IDs of branches and bifurcation.
        key (str): Type of points to extract.
        R (ndarray): Matrix containing unit vectors in the rotated coordinate system.
        m (dict): Cointains rotation matrices for each daughter branch.
        rotated (bool): Gets rotated points if True.
        bif (true): Gets only bifurcation points if True.

    Returns:
        points (vtkPoints): Points as VTK objects.
    Returns:
        div_points_bif (ndarray): Points as numpy objects.
    """
    div_points = np.asarray([data["bif"][key], data[0][key], data[1][key]])

    # Origo of the bifurcation
    O_key = "div_point"
    O = np.asarray([data["bif"][O_key], data[0][O_key], data[1][O_key]])
    O = np.sum(np.asarray(O), axis=0) / 3.

    if rotated:
        R_inv = np.linalg.inv(R)
        for i in range(len(div_points)):
            m_ = m[i] if i > 0 else np.eye(3)
            div_points[i] = np.dot(np.dot(np.dot(div_points[i] - O, R), m_), R_inv) + O

    # Insert landmarking points into VTK objects
    points = vtk.vtkPoints()
    div_points_bif = div_points[bif:]
    for point in div_points_bif:
        points.InsertNextPoint(point)

    return points, div_points_bif


def rotate_voronoi(clipped_voronoi, patch_cl, div_points, m, R):
    """
    Perform rotation of the voronoi diagram representing the
    daughter branches. Rotate along the bifurcation plane
    spanned by two vectors, preserving the angle with
    the rest of the vasculature. Rotation is performed
    using a standard rotational matrix m.

    Args:
        clipped_voronoi (vtkPolyData): Clipped voronoi diagram.
        patch_cl (vtkPolyData): Clipped centerline.
        div_points (ndarray): Contains bifurcation landmarking points.
        R (ndarray): Matrix containing unit vectors in the rotated coordinate system.
        m (dict): Cointains rotation matrices for each daughter branch.
    Returns:
        maskedVoronoi (vtkPolyData): Rotated voronoi diagram.
    """
    numberOfPoints = clipped_voronoi.GetNumberOfPoints()
    distance = vtk.vtkMath.Distance2BetweenPoints
    I = np.eye(3)
    R_inv = np.linalg.inv(R)

    locator = []
    cellLine = []
    not_rotate = [0]
    for i in range(patch_cl.GetNumberOfCells()):
        cellLine.append(extract_single_line(patch_cl, i))
        tmp_locator = get_locator(cellLine[-1])
        locator.append(tmp_locator)

    for i in range(1, patch_cl.GetNumberOfCells()):
        pnt = cellLine[i].GetPoints().GetPoint(0)
        new = cellLine[0].GetPoints().GetPoint(locator[0].FindClosestPoint(pnt))
        dist = math.sqrt(distance(pnt, new)) < divergingRatioToSpacingTolerance
        if dist:
            not_rotate.append(i)

    def check_rotate(point):
        dist = []
        for i in range(len(locator)):
            tmp = locator[i].FindClosestPoint(point)
            tmp = cellLine[i].GetPoints().GetPoint(tmp)
            dist.append(math.sqrt(distance(tmp, point)))

        if dist.index(min(dist)) not in not_rotate:
            pnt = cellLine[dist.index(min(dist))].GetPoints().GetPoint(0)
            if math.sqrt(distance(pnt, div_points[1])) > \
                    math.sqrt(distance(pnt, div_points[2])):
                m_ = m[2]
                div = div_points[2]
            else:
                m_ = m[1]
                div = div_points[1]
            return m_, div
        else:
            return I, np.array([0, 0, 0])

    maskedVoronoi = vtk.vtkPolyData()
    maskedPoints = vtk.vtkPoints()
    cellArray = vtk.vtkCellArray()
    radiusArray = get_vtk_array(radiusArrayName, 1, numberOfPoints)

    # Iterate through voronoi diagram
    for i in range(numberOfPoints):
        point = [0.0, 0.0, 0.0]
        clipped_voronoi.GetPoint(i, point)

        pointRadius = clipped_voronoi.GetPointData().GetArray(radiusArrayName).GetTuple1(i)
        M, O = check_rotate(point)
        tmp = np.dot(np.dot(np.dot(np.asarray(point) - O, R), M), R_inv) + O
        maskedPoints.InsertNextPoint(tmp)
        radiusArray.SetTuple1(i, pointRadius)
        cellArray.InsertNextCell(1)
        cellArray.InsertCellPoint(i)

    maskedVoronoi.SetPoints(maskedPoints)
    maskedVoronoi.SetVerts(cellArray)
    maskedVoronoi.GetPointData().AddArray(radiusArray)

    return maskedVoronoi


def rotate_cl(patch_cl, div_points, rotation_matrix, R):
    """
    Perform rotation of the centerline representing the
    daughter branches. Rotate along the bifurcation plane
    spanned by two vectors, preserving the angle with
    the rest of the vasculature. Rotation is performed
    using a standard rotational matrix.

    Args:
        patch_cl (vtkPolyData): Clipped centerline representing two daughter branches.
        div_points (ndarray): Contains bifurcation landmarking points.
        rotation_matrix (dict): Cointains rotation matrices for each daughter branch.
        R (ndarray): Matrix containing unit vectors in the rotated coordinate system.
    Returns:
        centerlin (vtkPolyData): Rotated centerline.
    """
    distance = vtk.vtkMath.Distance2BetweenPoints
    I = np.eye(3)
    R_inv = np.linalg.inv(R)

    numberOfPoints = patch_cl.GetNumberOfPoints()

    centerline = vtk.vtkPolyData()
    centerlinePoints = vtk.vtkPoints()
    centerlineCellArray = vtk.vtkCellArray()
    radiusArray = get_vtk_array(radiusArrayName, 1, numberOfPoints)

    line0 = extract_single_line(patch_cl, 0)
    locator0 = get_locator(line0)

    # Iterate through points along the centerline
    count = 0
    for i in range(patch_cl.GetNumberOfCells()):
        cell = extract_single_line(patch_cl, i)
        centerlineCellArray.InsertNextCell(cell.GetNumberOfPoints())

        start = cell.GetPoint(0)
        dist = line0.GetPoint(locator0.FindClosestPoint(start))
        test = math.sqrt(distance(start, dist)) > divergingRatioToSpacingTolerance

        if test or len(div_points) == 2:
            locator = get_locator(cell)

            pnt1 = cell.GetPoint(locator.FindClosestPoint(div_points[-2]))
            pnt2 = cell.GetPoint(locator.FindClosestPoint(div_points[-1]))
            dist1 = math.sqrt(distance(pnt1, div_points[-2]))
            dist2 = math.sqrt(distance(pnt2, div_points[-1]))
            k = -2 if dist1 < dist2 else -1
            O = div_points[k]
            m = rotation_matrix[k + 3]

        else:
            m = I
            O = np.array([0, 0, 0])

        getData = cell.GetPointData().GetArray(radiusArrayName).GetTuple1
        for j in range(cell.GetNumberOfPoints()):
            point = np.asarray(cell.GetPoints().GetPoint(j))
            tmp = np.dot(np.dot(np.dot(point - O, R), m), R_inv) + O
            centerlinePoints.InsertNextPoint(tmp)
            radiusArray.SetTuple1(count, getData(j))
            centerlineCellArray.InsertCellPoint(count)
            count += 1

    centerline.SetPoints(centerlinePoints)
    centerline.SetLines(centerlineCellArray)
    centerline.GetPointData().AddArray(radiusArray)

    return centerline


def rotation_matrix(data, angle, leave1, leave2):
    """
    Compute the rotation matrices for one or both
    daughter brances of the vessel.

    Args:
        data  (dict): Contains information about landmarking points.
        angle (float): Angle which brances are rotated.
        leave1 (bool): Leaves first daughter branch if True.
        leave2 (bool): Leaves second daughter branch if True.

    Returns:
        R (ndarray): Matrix containing unit vectors in the rotated coordinate system.
    Returns:
        m (dict): Cointains rotation matrices for each daughter branch.
    """

    # Create basis vectors defining bifurcation plane
    d = (np.asarray(data[0]["div_point"]) + \
         np.asarray(data[1]["div_point"]) + \
         np.asarray(data["bif"]["div_point"])) / 3.
    vec = np.eye(3)
    for i in range(2):
        e = np.asarray(data[i]["end_point"])
        tmp = e - d
        len = math.sqrt(np.dot(tmp, tmp))
        vec[:, i] = tmp / len

    # Expand basis to 3D
    R = gram_schmidt(vec)

    # Set up rotation matrices
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    m1 = np.asarray([[cos_a, -sin_a, 0],
                     [sin_a, cos_a, 0],
                     [0, 0, 1]])
    m2 = np.asarray([[cos_a, sin_a, 0],
                     [-sin_a, cos_a, 0],
                     [0, 0, 1]])

    m = {1: m1, 2: m2}
    tmp1 = data[0]["div_point"] - d
    tmp2 = data[1]["div_point"] - d

    I = np.eye(3)

    if np.dot(tmp1, R)[0] > np.dot(tmp2, R)[0]:
        m = {1: m2, 2: m1}

    # Leave one of the branches untouched
    if leave1:
        k = 1
        m[k] = I
    if leave2:
        k = 2
        m[k] = I

    return R, m


def merge_cl(centerline, end_point, div_point):
    """
    Merge overlapping centerliens.

    Args:
        centerline (vtkPolyData): Centerline data consisting of multiple lines.
        end_point (ndarray): Point where bifurcation ends.
        div_point (ndarray): Point where centerlines diverge.

    Returns:
        merge (vtkPolyData): Merged centerline.
    """
    merge = vtk.vtkPolyData()
    points = vtk.vtkPoints()
    cellArray = vtk.vtkCellArray()
    N_lines = centerline.GetNumberOfLines()

    arrays = []
    N_, names = get_number_of_arrays(centerline)
    for i in range(N_):
        tmp = centerline.GetPointData().GetArray(names[i])
        tmp_comp = tmp.GetNumberOfComponents()
        array = get_vtk_array(names[i], tmp_comp, centerline.GetNumberOfPoints())
        arrays.append(array)

    # Find lines to merge
    lines = [extract_single_line(centerline, i) for i in range(N_lines)]
    locators = [get_locator(lines[i]) for i in range(N_lines)]
    div_ID = [locators[i].FindClosestPoint(div_point[0]) for i in range(N_lines)]
    end_ID = [locators[i].FindClosestPoint(end_point[0]) for i in range(N_lines)]
    dist = [np.sum(lines[i].GetPoint(end_ID[i]) - end_point[0]) for i in range(N_lines)]

    # Find the direction of each line
    map_other = {0: 1, 1: 0}
    ID0 = locators[0].FindClosestPoint(end_point[1])
    ID1 = locators[1].FindClosestPoint(end_point[1])
    dist0 = math.sqrt(np.sum((np.asarray(lines[0].GetPoint(ID0)) - end_point[1]) ** 2))
    dist1 = math.sqrt(np.sum((np.asarray(lines[1].GetPoint(ID1)) - end_point[1]) ** 2))
    end1 = 0 if dist0 < dist1 else 1
    end2 = int(not end1)
    for i in range(2, N_lines):
        ID1 = locators[i].FindClosestPoint(end_point[1])
        ID2 = locators[i].FindClosestPoint(end_point[2])
        dist1 = math.sqrt(np.sum((np.asarray(lines[i].GetPoint(ID1)) - end_point[1]) ** 2))
        dist2 = math.sqrt(np.sum((np.asarray(lines[i].GetPoint(ID2)) - end_point[2]) ** 2))
        map_other[i] = end1 if dist1 > dist2 else end2

    counter = 0
    for i in range(centerline.GetNumberOfLines()):
        line = lines[i]

        # Check if it should be merged
        loc = get_locator(line)
        clipp_id = loc.FindClosestPoint(end_point[0])
        div_id = loc.FindClosestPoint(div_point[0])
        clipp_dist = distance(line.GetPoint(clipp_id), end_point[0])
        div_dist = distance(line.GetPoint(div_id), div_point[0])
        tol = get_tolerance(line) * 3
        merge_bool = True
        if clipp_dist > tol or div_dist > tol:
            merge_bool = False

        # Get the other line
        other = lines[map_other[i]]
        N = line.GetNumberOfPoints()
        cellArray.InsertNextCell(N)

        for j in range(N):
            # Add point
            if div_ID[i] < j < end_ID[i] and merge_bool:
                new = (np.asarray(other.GetPoint(j)) +
                       np.asarray(line.GetPoint(j))) / 2.
                points.InsertNextPoint(new)
            else:
                points.InsertNextPoint(line.GetPoint(j))

            cellArray.InsertCellPoint(counter)

            # Add array
            for k in range(N_):
                num = arrays[k].GetNumberOfComponents()
                if num == 1:
                    tmp = line.GetPointData().GetArray(names[k]).GetTuple1(j)
                    arrays[k].SetTuple1(counter, tmp)
                elif num == 3:
                    tmp = line.GetPointData().GetArray(names[k]).GetTuple3(j)
                    arrays[k].SetTuple3(counter, tmp[0], tmp[1], tmp[2])
                else:
                    print("Add more options")
                    sys.exit(0)

            counter += 1

    # Insert points, lines and arrays
    merge.SetPoints(points)
    merge.SetLines(cellArray)
    for i in range(N_):
        merge.GetPointData().AddArray(arrays[i])

    return merge


def read_command_line():
    """
    Read arguments from commandline
    """

    description = "Removes the bifurcation (possibly with an aneurysm), after which the" + \
                  " daughter branches can be rotated."
    parser = ArgumentParser(description=description, formatter_class=RawDescriptionHelpFormatter)
    required = parser.add_argument_group('required named arguments')

    # Required arguments
    required.add_argument('-i', '--ifile', type=str, default=None, required=True,
                          help="Path to the input surface.")
    required.add_argument("-o", "--ofile", type=str, default=None, required=True,
                          help="Path to the manipulated surface.")

    # General arguments
    parser.add_argument("-m", "--method", type=str, default="variation",
                        choices=["variation", "stenosis", "area"],
                        help="Methods for manipulating the area in the region of interest:" + \
                             "\n1) 'variation' will increase or decrease the changes in area" + \
                             " along the centerline of the region of interest." + \
                             "\n2) 'stenosis' will create or remove a local narrowing of the" + \
                             " surface. If two points is provided, the area between these" + \
                             " two points will be linearly interpolated to remove the narrowing." + \
                             " If only one point is provided it is assumed to be the center of" + \
                             " the stenosis. The new stenosis will have a sin shape, however, any" + \
                             " other shape may be easly implemented." + \
                             "\n3) 'area' will inflate or deflate the area in the region of" + \
                             " interest.")
    parser.add_argument('-s', '--smooth', type=str2bool, default=True,
                        help="Smooth the voronoi diagram, default is False")
    parser.add_argument('-f', '--smooth_factor', type=float, default=0.25,
                        help="If smooth option is true then each voronoi point" + \
                             " that has a radius less then MISR*(1-smooth_factor) at" + \
                             " the closest centerline point is removed.")
    parser.add_argument("-n", "--no_smooth", type=bool, default=False,
                        help="If true and smooth is true the user, if no_smooth_point is" + \
                             " not given, the user can provide points where the surface not will" + \
                             " be smoothed.")
    parser.add_argument("--no_smooth_point", nargs="+", type=float, default=None,
                        help="If model is smoothed the user can manually select points on" + \
                             " the surface that will not be smoothed. A centerline will be" + \
                             " created to the extra point, and the section were the centerline" + \
                             " differ from the other centerlines will be keept un-smoothed. This" + \
                             " can be practicle for instance when manipulating geometries" + \
                             " with aneurysms")
    parser.add_argument("-b", "--poly-ball-size", nargs=3, type=int, default=[120, 120, 120],
                        help="The size of the poly balls that will envelope the new" + \
                             " surface. The default value is 120, 120, 120. If two tubular" + \
                             " structures are very close compared to the bounds, the poly ball" + \
                             " size should be adjusted. For quick proto typing we" + \
                             " recommend ~100 in all directions, but >250 for a final " + \
                             " surface.", metavar="size")
        # Set region of interest:
    parser.add_argument("-r", "--region-of-interest", type=str, default="manuall",
                        choices=["manuall", "commandline"],
                        help="The method for defining the region to be changed. There are" +
                             " three options: 'manuall', 'commandline', 'landmarking'. In" +
                             " 'manuall' the user will be provided with a visualization of the" +
                             " input surface, and asked to provide an end and start point of the" +
                             " region of interest. Note that not all algorithms are robust over" +
                             " bifurcations. If 'commandline' is provided, then '--region-points'" +
                             " is expected to be provided. Finally, if 'landmarking' is" +
                             " given, it will look for the output from running" +
                             " automated_geometric_quantities.py.")
    parser.add_argument("--region-points", nargs="+", type=float, default=None, metavar="points",
                        help="If -r or --region-of-interest is 'commandline' then this" +
                             " argument have to be given. The method expects two points" +
                             " which defines the start and end of the region of interest. If" +
                             " 'method' is set to stenosis, then one point can be provided as well," +
                             " which is assumbed to be the center of a new stenosis." +
                             " Example providing the points (1, 5, -1) and (2, -4, 3):" +
                             " --stenosis-points 1 5 -1 2 -4 3")

    # Arguments for rotation
    parser.add_argument('-a', '--angle', type=float, default=10,
                        help="Each daughter branch is rotated an angle 'a' in the" +
                             " bifurcation plane. 'a' is assumed to be in degrees," + \
                             " and not radians", metavar="rotation_angle")
    parser.add_argument("--keep-fixed-1", type=bool, default=False,
                        help="Leave one branch untuched")
    parser.add_argument("--keep-fixed-2", type=bool, default=False,
                        help="Leave one branch untuched")

    # Bifurcation reconstruction arguments
    parser.add_argument("--bif", type=bool, default=False,
                        help="interpolate bif as well")
    parser.add_argument("--lower", type=bool, default=False,
                        help="Make a fourth line to interpolate along that" +
                             " is lower than the other bif line.")
    parser.add_argument("--cylinder_factor", type=float, default=7.0,
                        help="Factor for choosing the smaller cylinder")
    parser.add_argument("--version", type=bool, default=True, help="Type of" +
                                                                   "interpolation")
                        # TODO: Expand explanation
    parser.add_argument("--resampling-step", type=float, default=0.1,
                        help="Resampling step used to resample centerlines")

    args = parser.parse_args()
    ang_ = 0 if args.angle == 0 else args.angle * math.pi / 180  # Convert from deg to rad

    return dict(input_filepath=args.ifile, smooth=args.smooth, output_filepath=args.ofile,
                smooth_factor=args.smooth_factor, angle=ang_,
                keep_fixed_1=args.keep_fixed_1, keep_fixed_2=args.keep_fixed_2,
                bif=args.bif, lower=args.lower, cylinder_factor=args.cylinder_factor,
                resampling_step=args.resampling_step, no_smooth=args.no_smooth,
                no_smooth_point=args.no_smooth_point, poly_ball_size=args.poly_ball_size,
                version=args.version, region_of_interest=args.region_of_interest,
                region_points=args.region_points)


if __name__ == "__main__":
    rotate_branches(**read_command_line())