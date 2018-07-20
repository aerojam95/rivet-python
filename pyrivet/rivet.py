import time

from . import barcode
import subprocess
import shlex
import fractions
import tempfile
import os
import shutil

"""An interface for rivet_console, using the command line
and subprocesses."""

rivet_executable = 'rivet_console'


class Point:
    def __init__(self, appearance, *coords):
        self.appearance = appearance
        self.coords = coords

    @property
    def dimension(self):
        return len(self.coords)


def points(tuples, appearance=0):
    return [Point(appearance, *tup) for tup in tuples]


class PointCloud:
    def __init__(self, points, second_param_name=None,
                 comments=None, max_dist=None):
        if second_param_name:
            self.second_param_name = second_param_name
        else:
            self.second_param_name = None
        self.points = points
        self.comments = comments
        self.dimension = points[0].dimension
        for i, p in enumerate(points):
            if p.dimension != self.dimension:
                raise ValueError("Expected points of dimension %d,"
                                 " but point at position %d has dimension %d"
                                 % (self.dimension, i, p.dimension))
        self.max_dist = max_dist or self._calc_max_dist()

    def _calc_max_dist(self):
        # Simplest possible max distance measure
        lo, hi = 0, 0
        for p in self.points:
            for coord in p.coords:
                if coord < lo:
                    lo = coord
                if coord > hi:
                    hi = coord
        return abs(hi - lo)

    def save(self, out):
        if self.comments:
            out.writelines(["# " + line + "\n"
                            for line in str(self.comments).split("\n")])
        out.write("points\n")
        out.write(str(self.dimension) + "\n")
        out.write('{:f}'.format(self.max_dist) + "\n")
        if self.second_param_name is not None:
            out.write(self.second_param_name + "\n")
        else:
            out.write("no function\n")
        for p in self.points:
            for c in p.coords:
                out.write('{:f}'.format(c))
                out.write(" ")
            if self.second_param_name is not None:
                out.write('{:f} '.format(p.appearance))
            out.write("\n")
        out.write("\n")


class Bifiltration:
    def __init__(self, x_label, y_label, points):
        self.x_label = x_label
        self.y_label = y_label
        self.points = points
        for p in self.points:
            if not hasattr(p.appearance, '__len__') or len(p.appearance) != 2:
                raise ValueError(
                    "For a bifiltration, points must have a 2-tuple in the appearance field")

    def save(self, out):
        out.write('bifiltration\n')
        out.write(self.x_label + '\n')
        out.write(self.y_label + '\n')
        for p in self.points:
            for c in p.coords:
                out.write('{:f} '.format(c))
                out.write(" ")
            for b in p.appearance:
                out.write('{:f} '.format(b))
                out.write(" ")
            out.write("\n")
        out.write("\n")


# To make multi_critical (with no appearance_values), initialize with appearance_values=None
# TODO: set appearance_values to None by default
class MetricSpace:
    def __init__(self, appearance_label, distance_label, appearance_values, distance_matrix, comment=None):
        """distance_matrix must be upper triangular"""
        self.comment = comment
        self.appearance_label = appearance_label
        self.distance_label = distance_label
        self.appearance_values = appearance_values
        self.distance_matrix = distance_matrix

    def save(self, out):
        out.seek(0)
        out.truncate()
        out.write('metric\n')
        if self.comment:
            out.write('#')
            out.write(self.comment.replace('\n', '\n#'))
            out.write('\n')
        if self.appearance_values is not None:
            out.write(self.appearance_label + '\n')
            out.write(" ".join(['{:f} '.format(s) for s in self.appearance_values]) + "\n")
        else:
            out.write("no function\n")
            out.write(str(len(self.distance_matrix)) + "\n")
        out.write(self.distance_label + '\n')
        dim = len(self.distance_matrix)
        max_dist = max(*[self.distance_matrix[i][j] for i in range(dim) for j in range(dim)])
        out.write('{:f}'.format(max_dist) + '\n')
        for row in range(dim):
            for col in range(row + 1, dim):
                # This line determines the precise representation of the output format.
                out.write('{:f} '.format(self.distance_matrix[row][col]))
            out.write('\n')


def compute_point_cloud(cloud, homology=0, x=0, y=0, verify=False):
    return _compute_bytes(cloud, homology, x, y, verify)


def compute_bifiltration(bifiltration, homology=0, verify=False):
    return _compute_bytes(bifiltration, homology, 0, 0, verify)


def compute_metric_space(metric_space, homology=0, x=0, y=0, verify=False):
    return _compute_bytes(metric_space, homology, x, y, verify)


def _compute_bytes(saveable, homology, x, y, verify):
    with TempDir() as dir:
        saveable_name = os.path.join(dir, 'rivet_input_data.txt')
        with open(saveable_name, 'w+t') as saveable_file:
            saveable.save(saveable_file)
        output_name = compute_file(saveable_name,
                                   homology=homology,
                                   x=x,
                                   y=y)
        with open(output_name, 'rb') as output_file:
            output = output_file.read()
        if verify:
            assert bounds(output)
        return output


def barcodes(bytes, slices):
    """Returns a Barcode for each (angle, offset) tuple in `slices`."""
    with TempDir() as dir:
        with open(os.path.join(dir, 'precomputed.rivet'), 'wb') as precomp:
            precomp.write(bytes)
        with open(os.path.join(dir, 'slices.txt'), 'wt') as slice_temp:
            for angle, offset in slices:
                slice_temp.write("%s %s\n" % (angle, offset))
        return barcodes_file(precomp.name, slice_temp.name)


def _rivet_name(base, homology, x, y):
    output_name = base + (".H%d_x%d_y%d.rivet" % (homology, x, y))
    return output_name


def compute_file(input_name, output_name=None, homology=0, x=0, y=0):
    if not output_name:
        output_name = _rivet_name(input_name, homology, x, y)
    cmd = "%s %s %s -H %d -x %d -y %d -f msgpack" % \
          (rivet_executable, input_name, output_name, homology, x, y)
    subprocess.check_output(shlex.split(cmd))
    return output_name


def barcodes_file(input_name, slice_name):
    cmd = "%s %s --barcodes %s" % (rivet_executable, input_name, slice_name)
    return _parse_slices(
        subprocess.check_output(
            shlex.split(cmd)).split(b'\n'))


def betti(saveable, homology=0, x=0, y=0):
    # print("betti")
    with TempDir() as dir:
        name = os.path.join(dir, 'rivet-input.txt')
        with open(name, 'wt') as betti_temp:
            saveable.save(betti_temp)
        return betti_file(name, homology=homology, x=x, y=y)


def betti_file(name, homology=0, x=0, y=0):
    cmd = "%s %s --betti -H %d -x %d -y %d" % (rivet_executable, name, homology, x, y)
    return _parse_betti(subprocess.check_output(shlex.split(cmd)).split(b'\n'))


def bounds_file(name):
    cmd = "%s %s --bounds" % (rivet_executable, name)
    return parse_bounds(subprocess.check_output(shlex.split(cmd)).split(b'\n'))


class TempDir(os.PathLike):
    def __enter__(self):
        self.dirname = os.path.join(tempfile.gettempdir(),
                                    'rivet-' + str(os.getpid()) + '-' + str(time.time()))
        os.mkdir(self.dirname)

        return self

    def __exit__(self, etype, eval, etb):
        if etype is None:
            shutil.rmtree(self.dirname, ignore_errors=True)
        else:
            print("Error occurred, leaving RIVET working directory intact: " + self.dirname)

    def __str__(self):
        return self.dirname

    def __fspath__(self):
        return self.dirname


def bounds(bytes):
    # print("bounds", len(bytes), "bytes")
    assert len(bytes) > 0
    with TempDir() as dir:
        precomp_name = os.path.join(dir, 'precomp.rivet')
        with open(precomp_name, 'wb') as precomp:
            precomp.write(bytes)
        return bounds_file(precomp_name)


class Bounds:
    """The lower left and upper right corners of a rectangle, used to capture the parameter range for a RIVET
    2-parameter persistence module"""

    def __init__(self, lower_left, upper_right):
        self.lower_left = lower_left
        self.upper_right = upper_right

    def __repr__(self):
        return "Bounds(lower_left=%s, upper_right=%s)" % (self.lower_left, self.upper_right)

    def common_bounds(self, other: 'Bounds'):
        """Returns a minimal Bounds that encloses both self and other"""

        # TODO: rename to 'union'?
        # the lower left bound taken to be the min for the two modules,
        # and the upper right taken to be the max for the two modules.
        lower_left = [min(self.lower_left[0], other.lower_left[0]),
                      min(self.lower_left[1], other.lower_left[1])]
        upper_right = [max(self.upper_right[0], other.upper_right[0]),
                       max(self.upper_right[1], other.upper_right[1])]
        return Bounds(lower_left, upper_right)


def parse_bounds(lines):
    low = (0, 0)
    high = (0, 0)
    for line in lines:
        line = str(line, 'utf-8')
        line = line.strip()
        if line.startswith('low:'):
            parts = line[5:].split(",")
            low = tuple(map(float, parts))
        if line.startswith('high:'):
            parts = line[6:].split(",")
            high = tuple(map(float, parts))
    return Bounds(low, high)


class Dimensions:
    def __init__(self, x_grades, y_grades, ):
        self.x_grades = x_grades
        self.y_grades = y_grades

    def __repr__(self):
        return "Dimensions(%s, %s)" % (self.x_grades, self.y_grades)

    def __eq__(self, other):
        return isinstance(other, Dimensions) \
               and self.x_grades == other.x_grades \
               and self.y_grades == other.y_grades


class MultiBetti:
    def __init__(self, dims: Dimensions, xi_0, xi_1, xi_2):
        self.dimensions = dims
        self.xi_0 = xi_0
        self.xi_1 = xi_1
        self.xi_2 = xi_2

    def __repr__(self):
        return "MultiBetti(%s, %s, %s, %s)" % \
               (self.dimensions, self.xi_0, self.xi_1, self.xi_2)


def _parse_betti(text):
    x_grades = []
    y_grades = []
    current_grades = None
    xi = [[], [], []]

    current_xi = None

    for line in text:
        line = line.strip()
        if len(line) == 0:
            line = None
        else:
            line = str(line, 'utf-8')
        if line == 'x-grades':
            current_grades = x_grades
        elif line == 'y-grades':
            current_grades = y_grades
        elif line is None:
            current_grades = None
            current_xi = None
        elif current_grades is not None:
            current_grades.append(fractions.Fraction(line))
        elif line.startswith('xi_'):
            current_xi = xi[int(line[3])]
        elif current_xi is not None:
            current_xi.append(tuple(map(int, line[1:-1].split(','))))

    return MultiBetti(Dimensions(x_grades, y_grades), *xi)


def _parse_slices(text):
    slices = []
    for line in text:
        line = line.strip()
        if not line:
            continue
        header, body = line.split(b':')
        angle, offset = header.split(b' ')
        bars = []
        for part in body.split(b','):
            part = part.strip()
            if not part:
                continue
            birth, death, mult = part.split(b' ')
            bars.append(barcode.Bar(float(birth), float(death), int(mult[1:])))

        code = barcode.Barcode(bars)
        slices.append(((float(angle), float(offset)), code))
    return slices