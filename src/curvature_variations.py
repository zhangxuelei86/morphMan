from common import *
from argparse import ArgumentParser
from os import path, listdir

# Local import
from patchandinterpolatecenterlines import *
from clipvoronoidiagram import *
from paralleltransportvoronoidiagram import *
from moveandmanipulatetools import *


def read_command_line():
    """Read arguments from commandline"""
    parser = ArgumentParser()

    parser.add_argument('-d', '--dir_path', type=str, default=".",
                        help="Path to the folder with all the cases")
    parser.add_argument('-case', type=str, default=None, help="Choose case")
    parser.add_argument('-s', '--smooth', type=bool, default=False,
                        help="If the original voronoi diagram (surface) should be" + \
                        "smoothed before it is manipulated", metavar="smooth")
    parser.add_argument("-sf", "--smoothingfactor", type=float, default=1.0,
                        help="Smoothing factor of centerline curve.")
    parser.add_argument("-sf_voro", "--smoothingfactor_voro", type=float, default=0.25,
                         help="If smooth option is true then each voronoi point" + \
                         " that has a radius less then MISR*(1-smooth_factor) at" + \
                         " the closest centerline point is removes" metavar="smoothening_factor")
    parser.add_argument("-sm", "--smoothmode", type=str2bool, default=True,
                        help="Smoothes centerline if True, anti-smoothes if False", metavar="smoothmode")
    parser.add_argument("-it", "--iterations", type=int, default=100,
                        help="Smoothing iterations of centerline curve.")

    args = parser.parse_args()

    return args.smooth, args.dir_path, args.case, args.smoothmode, args.smoothingfactor, \
           args.iterations, args.smoothingfactor_voro


def change_curvature(dirpath, name, smooth, smoothingfactor, iterations, smoothmode, smooth_factor_voro):
    """
    Create a sharper or smoother version of the input geometry,
    determined by a smoothed version of the siphon centerline.

    Args:
        dirpath (str): Directory where case is located.
        name (str): Directory where surface models are located.
        smooth (bool): Adjusts smoothing of the voronoi diagram.
        smoothingfactor (float): Smoothingfactor for centerline smoothing.
        iterations (int): Number of smoothing iterations.
        smoothmode (bool): Determines if models is sharpened or smoothed.
    """
    it = iterations
    sf = smoothingfactor

    # Input filenames
    model_path = path.join(dirpath, name, "model.vtp")

    # Output names
    model_smoothed_path = path.join(dirpath, name, "model_smoothed.vtp")
    method = "smoothed" if smoothmode else "extended"
    model_new_surface = path.join(dirpath, name, "model_%s_fac_%s_it_%s.vtp" % (method, sf, it))
    model_new_surface_clean = path.join(dirpath, name , "model_%s_fac_%s_it_%s_clean.vtp" % ( method, sf, it))

    # Centerlines
    centerline_complete_path = path.join(dirpath, name, "centerline_complete.vtp")
    centerline_clipped_path = path.join(dirpath, name, "centerline_clipped.vtp")
    centerline_clipped_part_path = path.join(dirpath, name, "centerline_clipped_part.vtp")
    centerline_clipped_part1_path = path.join(dirpath, name, "centerline_clipped_end_part.vtp")
    centerline_new_path = path.join(dirpath, name, "centerline_interpolated.vtp")
    carotid_siphon_path = path.join(dirpath, name, "carotid_siphon.vtp")
    centerline_smooth_path = path.join(dirpath, name, "smooth_carotid_siphon.vtp")

    # Voronoi diagrams
    voronoi_path = path.join(dirpath, name, "model_voronoi.vtp")
    voronoi_smoothed_path = path.join(dirpath, name, "model_voronoi_smoothed.vtp")
    voronoi_clipped_path = path.join(dirpath, name, "model_voronoi_clipped.vtp")
    voronoi_clipped_part_path = path.join(dirpath, name, "model_voronoi_clipped_part.vtp")

    # Read and check model
    if not path.exists(model_path):
        RuntimeError("The given directory: %s did not contain the file: model.vtp" % dirpath)

    # Clean and capp / uncapp surface
    parameters = get_parameters(dirpath)
    open_surface, capped_surface = preare_surface(model_path, parameters)
    surface = open_surface

    # Get inlet and outlets
    inlet, outlets = get_centers(open_surface, dirpath)

    # Compute all centerlines
    centerlines_complete = compute_centerlines(inlet, outlets,
                                               centerline_complete_path,
                                               capped_surface, resampling=0.1)
    centerlines_in_order = sort_centerlines(centerlines_complete)

    print("Compute voronoi diagram")
    voronoi = prepare_voronoi_diagram(surface, model_smoothed_path, voronoi_path, voronoi_smoothed_path,
                                    smooth, smooth_factor_voro, centerlines_complete)

    # Get Carotid Siphon
    if path.exists(carotid_siphon_path):
        carotid_siphon = read_polydata(carotid_siphon_path)
    else:
        carotid_siphon = extract_carotid_siphon(dirpath)

    # Search for diverging clipping points along the siphon
    siphon_end_point = carotid_siphon.GetPoint(carotid_siphon.GetNumberOfPoints()-1)
    div_ids, div_points, centerlines_in_order, div_lines = find_diverging_centerlines(centerlines_in_order,
                                                                                      siphon_end_point)

    if div_ids != []:
        print("Clipping diverging centerlines")
        div_patch_cl = []
        for i, divline in enumerate(div_lines):
            clip_id = int((divline.GetNumberOfPoints() - div_ids[i])*0.2 + div_ids[i])
            patch_eye = clip_eyeline(divline, carotid_siphon.GetPoint(0), clip_id)
            div_patch_cl.append(extract_single_line(patch_eye, 1))

    # Clipp Voronoi diagram
    print("Clipping voronoi diagram")
    masked_voronoi = MaskVoronoiDiagram(voronoi, carotid_siphon)
    clipped_voronoi = ExtractMaskedVoronoiPoints(voronoi, masked_voronoi)

    # Extract voronoi diagram of diverging lines
    clipped_voronoi_div = []
    for div_line_ends in div_patch_cl:
        masked_voronoi_div = MaskVoronoiDiagram(voronoi, div_line_ends)
        clipped_voronoi_div.append(ExtractMaskedVoronoiPoints(voronoi, masked_voronoi_div))

    # Smooth Carotid siphon
    smooth_carotid_siphon = vmtk_centerline_geometry(carotid_siphon, True, True, factor=sf, iterations=it)
    write_polydata(smooth_carotid_siphon, centerline_smooth_path)

    # Get rest of artery
    locator = get_locator(carotid_siphon)
    pStart = carotid_siphon.GetPoint(0)
    pEnd = carotid_siphon.GetPoint(carotid_siphon.GetNumberOfPoints() - 1)
    clipping_points = [pStart, pEnd]
    div_points = np.asarray(clipping_points)
    points = vtk.vtkPoints()
    for point in div_points:
        points.InsertNextPoint(point)
    clip_points = points

    IDbif = locator.FindClosestPoint(pEnd)

    patch_cl = CreateParentArteryPatches(centerlines_in_order, clip_points, siphon=True)
    end_lines = []
    for i in range(patch_cl.GetNumberOfCells()):
        tmp_line = extract_single_line(patch_cl, i)
        if tmp_line.GetNumberOfPoints() > 50:
            end_lines.append(tmp_line)

    centerlines_end = merge_data(end_lines)
    masked_voronoi_end = MaskVoronoiDiagram(voronoi, centerlines_end)
    clipped_voronoi_end = ExtractMaskedVoronoiPoints(voronoi, masked_voronoi_end)

    # Update clipped Voronoi diagram
    print("Smooth / sharpen voronoi diagram")
    moved_clipped_voronoi = make_voronoi_smooth(clipped_voronoi, carotid_siphon, smooth_carotid_siphon, smoothmode)

    # Move diverging centerlines
    moved_clipped_voronoi_div = []
    for i, clipped_voronoi_div_i in enumerate(clipped_voronoi_div):
        moved_clipped_voronoi_div.append(make_voronoi_smooth(clipped_voronoi_div_i,
                                                             carotid_siphon,
                                                             smooth_carotid_siphon,
                                                             smoothmode, div=True,
                                                             div_point=div_points[i]))

    moved_clipped_voronoi_div.append(moved_clipped_voronoi)
    moved_clipped_voronoi_div.append(clipped_voronoi_end)

    # Combine Voronoi diagram
    newVoronoi = merge_data(moved_clipped_voronoi_div)

    # Create new surface
    print("Create new surface")
    new_surface = create_new_surface(newVoronoi)
    # TODO: Add Automated clipping of newmodel
    new_surface = vmtk_surface_smoother(new_surface, method="laplace", iterations=100)
    new_surface = clean_and_check_surface(new_surface, None,
                                          model_new_surface_clean, None)
    write_polydata(new_surface, model_new_surface)


def make_voronoi_smooth(voronoi, old_cl, new_cl, smoothmode, div=False, div_point=None):
    """
    Move the voronoi diagram based on a smoothed
    version of the centerline.

    Args:
        voronoi (vtkPolyData): Voronoi diagram data set.
        old_cl (vtkPolyData): Unsmoothed centerline points.
        new_cl (vtkPolyData): Smoothed centerline points.
        smoothmode (bool): Determines if model becomes smoother or sharper.
        div (bool): True if centerline is a diverging line.
        div_point (ndarray): Diverging point along siphon.

    Returns:
        newDataSet (vtkPolyData): Manipulated voronoi diagram.
    """
    locator = get_locator(old_cl)
    N = voronoi.GetNumberOfPoints()
    newDataSet = vtk.vtkPolyData()
    points = vtk.vtkPoints()
    verts = vtk.vtkCellArray()

    # Define segments for transitioning
    IDend = old_cl.GetNumberOfPoints() - 1
    IDmidend = int(IDend*0.9)
    IDstartmid = int(IDend*0.1)
    IDmid = int(IDend*0.2)
    # Iterate through voronoi points
    for i in range(N):
        if div:
            cl_id = locator.FindClosestPoint(div_point)
        else:
            cl_id = locator.FindClosestPoint(voronoi.GetPoint(i))
        p0 = np.asarray(old_cl.GetPoint(cl_id))
        p1 = np.asarray(new_cl.GetPoint(cl_id))
        if smoothmode:
            dx = p1 - p0
        else:
            dx = -(p1 - p0)

        # Smooth transition at inlet and at end of siphon
        if cl_id < IDstartmid:
            dx = 0
        elif IDstartmid <= cl_id < IDmid:
            dx = dx*(cl_id - IDstartmid) / float(IDmid - IDstartmid)
        elif cl_id > IDmidend:
            dx = dx*(IDend - cl_id) / float(IDend - IDmidend)

        dist = dx
        points.InsertNextPoint(np.asarray(voronoi.GetPoint(i)) + dist)
        verts.InsertNextCell(1)
        verts.InsertCellPoint(i)

    newDataSet.SetPoints(points)
    newDataSet.SetVerts(verts)
    newDataSet.GetPointData().AddArray(voronoi.GetPointData().GetArray(radiusArrayName))

    return newDataSet


if __name__ == "__main__":
    smooth, basedir, case, smoothmode, smoothingfactor, iterations, smooth_factor_voro = read_command_line()
    name = "surface"
    folders = listdir(basedir) if case is None else [case]
    for folder in folders:
        print("==== Working on case %s ====" % folder)
        dirpath = path.join(basedir, folder)
        change_curvature(dirpath, name, smooth, smoothingfactor, iterations, smoothmode, smooth_factor_voro)