import os
import struct

from . import common, iff

try:
    import bpy as blender
except:
    blender = None

def pr_debug(msg, *args, **kwargs):
    if not blender:
        print(msg, *args, **kwargs)

# IFF chunk type IDs
FOR4 = common.be_word4(b"FOR4")
LIS4 = common.be_word4(b"LIS4")
# 64 bits
FOR8 = common.be_word4(b"FOR8")
LIS8 = common.be_word4(b"LIS8")

# General
MAYA = common.be_word4(b"Maya")

# File referencing
FREF = common.be_word4(b"FREF")
FRDI = common.be_word4(b"FRDI")

# Header fields
HEAD = common.be_word4(b"HEAD")
VERS = common.be_word4(b"VERS")
PLUG = common.be_word4(b"PLUG")
FINF = common.be_word4(b"FINF")
AUNI = common.be_word4(b"AUNI")
LUNI = common.be_word4(b"LUNI")
TUNI = common.be_word4(b"TUNI")

# Node creation
CREA = common.be_word4(b"CREA")
SLCT = common.be_word4(b"SLCT")
ATTR = common.be_word4(b"ATTR")

CONS = common.be_word4(b"CONS")
CONN = common.be_word4(b"CONN")

# Data types
FLGS = common.be_word4(b"FLGS")
DBLE = common.be_word4(b"DBLE")
DBL3 = common.be_word4(b"DBL3")
STR_ = common.be_word4(b"STR ")
FLT2 = common.be_word4(b"FLT2")
CMPD = common.be_word4(b"CMPD")
MESH = common.be_word4(b"MESH")
NRBC = common.be_word4(b"NRBC")


MAYA_BINARY_32 = iff.IffFormat(
    endianness=iff.IFF_BIG_ENDIAN,
    typeid_bytes=4,
    size_bytes=4,
    header_alignment=4,
    chunk_alignment=4
)
MAYA_BINARY_64 = iff.IffFormat(
    endianness=iff.IFF_BIG_ENDIAN,
    typeid_bytes=4,
    size_bytes=8,
    header_alignment=8,
    chunk_alignment=8
)


class MayaBinaryError(RuntimeError):
    pass

class NurbsCurve(object):
    def __init__(self):
        self.control_points = []
        self.knot_vector = []
        self.degree = 3
        self.dimensions = 3

class MayaBinaryParser(iff.IffParser, common.MayaParserBase):
    def __init__(self, stream):
        # Determine Maya format based on magic number
        # Maya 2014+ files begin with a FOR8 block, indicating a 64-bit format.
        magic_number = stream.read(4)
        stream.seek(0)
        if magic_number == b"FOR4":
            format = MAYA_BINARY_32
        elif magic_number == b"FOR8":
            format = MAYA_BINARY_64
        else:
            raise MayaBinaryError("Bad magic number")

        iff.IffParser.__init__(self, stream, format=format)
        common.MayaParserBase.__init__(self)

        maya64 = format == MAYA_BINARY_64
        self.__maya64 = maya64
        self.__node_chunk_type = FOR8 if maya64 else FOR4
        self.__list_chunk_type = LIS8 if maya64 else LIS4

        # FIXME load type info modules based on maya and plugin versions
        self.__mtypeid_to_typename = {}
        self._load_mtypeid_database(os.path.join(os.path.dirname(__file__),
                                    "modules", "maya", "2012", "typeids.dat"))

    def on_iff_chunk(self, chunk):
        if chunk.typeid == self.__node_chunk_type:
            mtypeid = self._read_mtypeid()
            if mtypeid == MAYA:
                self._handle_all_chunks()
            elif mtypeid == HEAD:
                self._parse_maya_header()
            elif mtypeid == FREF:
                self._parse_file_reference()
            elif mtypeid == CONN:
                self._parse_connection()
            else:
                self._parse_node(mtypeid)

        elif chunk.typeid == self.__list_chunk_type:
            mtypeid = self._read_mtypeid()
            if mtypeid == CONS:
                self._handle_all_chunks()

    def _read_mtypeid(self):
        # 64-bit format still uses 32-bit MTypeIds
        result = common.be_read4(self.stream)
        self._realign()
        return result

    def _parse_maya_header(self):
        angle_unit = None
        linear_unit = None
        time_unit = None

        for chunk in self._iter_chunks():
            # requires (maya)
            if chunk.typeid == VERS:
                self.on_requires_maya(self._read_chunk_data(chunk).decode('ascii'))
            
            # requires (plugin)
            elif chunk.typeid == PLUG:
                plugin = common.read_null_terminated(self.stream)
                version = common.read_null_terminated(self.stream)
                self.on_requires_plugin(plugin, version)

            # fileInfo
            elif chunk.typeid == FINF:
                key = common.read_null_terminated(self.stream)
                value = common.read_null_terminated(self.stream)
                self.on_file_info(key, value)

            # on_current_unit callback is deferred until all three 
            # angle, linear and time units are read from the stream.

            # currentUnit (angle)
            elif chunk.typeid == AUNI:
                angle_unit = self._read_chunk_data(chunk).decode('ascii')

            # currentUnit (linear)
            elif chunk.typeid == LUNI:
                linear_unit = self._read_chunk_data(chunk).decode('ascii')

            # currentUnit (time)
            elif chunk.typeid == TUNI:
                time_unit = self._read_chunk_data(chunk).decode('ascii')

            # Got all three units
            if angle_unit and linear_unit and time_unit:
                self.on_current_unit(angle=angle_unit,
                                     linear=linear_unit,
                                     time=time_unit)
                angle_unit = None
                linear_unit = None
                time_unit = None

        # Didn't get all three units (this is non standard)
        if angle_unit or linear_unit or time_unit:
            self.on_current_unit(angle=angle_unit,
                                 linear=linear_unit,
                                 time=time_unit)

    def _parse_file_reference(self):
        for chunk in self._iter_chunks(types=[FREF]):
            self.on_file_reference(common.read_null_terminated(self.stream))

    def _parse_connection(self):
        self.stream.read(17 if self.__maya64 else 9)
        src = common.read_null_terminated(self.stream)
        dst = common.read_null_terminated(self.stream)
        self.on_connect_attr(src, dst)

    def _dump_chunk(self, chunk, hexdump=True, remaining=False):
        import codecs
        offset = self._get_offset()
        if remaining:
            data = self._read_remaining_chunk_data(chunk)
        else:
            data = self._read_chunk_data(chunk)
        self._set_offset(offset)

        def _hexdump(buf, start=0, width=16, indent=2):
            a = ''
            ret = ''
            for i, b in enumerate(buf):
                if i % width == 0:
                    if i:
                        ret += ' | %s |\n' % a
                    ret += '%s%08x: ' % (' ' * indent, start + i)
                    a = ''
                elif i and i % 4 == 0:
                    ret += ' '
                if b >= ord(' ') and b <= ord('~'):
                    a += chr(b)
                else:
                    a += '.'
                ret += '%02X' % b
            if a:
                rem = width - (i % width) - 1
                ret += ' ' * (rem*2)
                ret += ' ' * (rem//4 + 1)
                ret += '| %s%s |\n' % (a, ' ' * rem)
            return ret

        pr_debug('CHUNK \"%s\"' % struct.pack('>I', chunk.typeid).decode('ascii'))
        start = 0
        if remaining:
            start = offset - chunk.data_offset
            pr_debug('        ...:')
        if hexdump:
            #pr_debug(codecs.encode(data, 'hex'))
            pr_debug(_hexdump(data, start=start, indent=3), end='')

    def _parse_node(self, mtypeid):
        for chunk in self._iter_chunks():
            # Create node
            if chunk.typeid == CREA:
                typename = self.__mtypeid_to_typename.get(mtypeid, "unknown")
                name_parts = self._read_chunk_data(chunk)[1:-1].split(b"\0")
                name = name_parts[0].decode('ascii')
                try:
                    parent_name = name_parts[1].decode('ascii') if len(name_parts) > 1 else None
                except UnicodeDecodeError: # Some parent names are garbage
                    parent_name = name_parts[1]
                self.on_create_node(typename, name, parent=parent_name)

            # Select the current node
            elif chunk.typeid == SLCT:
                #self._dump_chunk(chunk)
                pass

            # Dynamic attribute
            elif chunk.typeid == ATTR:
                #self._dump_chunk(chunk)
                pass

            # Flags
            elif chunk.typeid == FLGS:
                #self._dump_chunk(chunk)
                pass

            # Set attribute
            else:
                self._parse_attribute(chunk.typeid, chunk)

    def _parse_attribute(self, mtypeid, chunk):
        # TODO Support more primitive types
        if mtypeid == STR_:
            self._parse_string_attribute()
        elif mtypeid == DBLE:
            self._parse_double_attribute()
        elif mtypeid == DBL3:
            self._parse_double3_attribute()
        elif mtypeid == NRBC:
            self._parse_nurbs_curve_attribute(chunk)
        else:
            self._dump_chunk(chunk, hexdump=False)
            self._parse_mpxdata_attribute(mtypeid)

    def _parse_attribute_info(self):
        attr_name = common.read_null_terminated(self.stream)
        self.stream.read(1)  # mystery flag
        count = common.plug_element_count(attr_name)
        return attr_name, count

    def _parse_string_attribute(self):
        attr_name, count = self._parse_attribute_info()
        value = common.read_null_terminated(self.stream)
        self.on_set_attr(attr_name, value, type="string")

    def _parse_double_attribute(self):
        attr_name, count = self._parse_attribute_info()
        value = struct.unpack(">" + "d" * count,
                              self.stream.read(8 * count))
        value = value[0] if count == 1 else value
        self.on_set_attr(attr_name, value, type="double")

    def _parse_double3_attribute(self):
        attr_name, count = self._parse_attribute_info()
        value = struct.unpack(">" + "ddd" * count,
                              self.stream.read(24 * count))
        self.on_set_attr(attr_name, value, type="double3")

    def _parse_nurbs_curve_attribute(self, chunk):
        self._dump_chunk(chunk)
        attr_name, count = self._parse_attribute_info()
        assert(attr_name == 'cc')
        assert(count == 1)

        curve = NurbsCurve()

        def struct_read(format):
            return struct.unpack(format, self.stream.read(struct.calcsize(format)))

        # Names are educated guesses, not certainties. "u" means unidentified.
        curve.degree, spans, u2, curve.dimensions, knots = struct_read(">2I5s2I")
        pr_debug('             Degree: %i' % curve.degree)
        pr_debug('             Spans?: %i' % spans) # Spans or "edit points" maybe?
        pr_debug('        Dimensions?: %i' % curve.dimensions)
        pr_debug('              Knots: %i' % knots)
        _points = knots - curve.degree + 1 # We will read this from the buffer "for real" later
        pr_debug('     Control Points: %i' % _points)

        # NOTE discrepancy:
        # Maya doco indicates: len(knots) == len(control_points) + degree - 1
        # Wikipedia indicates: len(knots) == len(control_points) + degree + 1
        # Maya binary format does seem consistent with Maya docs. Blender and
        # other NURBS implementations I've looked at seem consistent with
        # Wikipedia. It's possible that Maya implicitly duplicates or otherwise
        # calculates the 1st + last knot to account for this, but I need more data.

        # Making heavy use of asserts to catch any variants I haven't seen so I can make
        # sure they are interpreted correctly rather than risking passing garbage out.
        # Failing an assert may not mean there is a bug, but rather a guess I want to confirm.
        assert spans == _points - curve.degree, spans
        assert u2 == b'\0'*5, u2 # 5 bytes messes up 32bit alignment - perhaps an empty null terminated string somewhere here?
        assert curve.dimensions == 3, curve.dimensions # Complete guess, but maybe '4' will signify that W coords are present?

        #self._dump_chunk(chunk, remaining=True)

        for i in range(knots):
            knot, = struct_read(">d")
            pr_debug('            knot %2i: %f' % (i, knot))
            curve.knot_vector.append(knot)
            if i:
                assert knot >= prev_knot
            prev_knot = knot

        points, = struct_read(">I")
        assert points == _points

        for i in range(points):
            # Haven't come across any rational curves (i.e. with w components) yet.
            # Guessing that the '3' in the header will be a '4' in these cases
            # to signify 4 dimensional homogeneous coordinates, in which case
            # the below code will need to be adjusted. However, what if it's a
            # 2D rational curve (Blender has explicit support for 2D curves,
            # not sure about Maya) - that would need three dimensions to store
            # the weights, so how would it be distinguished from a 3D curve
            # without weights? Need to see these examples to know how to adjust
            # the below code, hence an assertion will fire if dimensions != 3.
            x, y, z, = struct_read(">3d")
            pr_debug('   control point %2i: %9f %9f %9f' % (i, x, y, z))
            curve.control_points.append((x, y, z))

        # Make sure we parsed the entire chunk (didn't fall short, didn't go over)
        assert(self._get_offset() == chunk.data_offset + chunk.data_length)

        self.on_set_attr(attr_name, curve, type="nurbsCurve")

    def _parse_mpxdata_attribute(self, typeid):
        # TODO
        pass

    def _load_mtypeid_database(self, path):
        with open(path, 'rb') as f:
            line = f.readline()
            while line:
                mtypeid = common.be_word4(line[:4])
                typename = line[5:].strip().decode('ascii')
                self.__mtypeid_to_typename[mtypeid] = typename
                line = f.readline()
