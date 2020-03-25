import os
import struct

from . import common, iff


# IFF chunk type IDs
FOR4 = common.be_word4("FOR4")
LIS4 = common.be_word4("LIS4")
# 64 bits
FOR8 = common.be_word4("FOR8")
LIS8 = common.be_word4("LIS8")

# General
MAYA = common.be_word4("Maya")

# File referencing
FREF = common.be_word4("FREF")
FRDI = common.be_word4("FRDI")

# Header fields
HEAD = common.be_word4("HEAD")
VERS = common.be_word4("VERS")
PLUG = common.be_word4("PLUG")
FINF = common.be_word4("FINF")
AUNI = common.be_word4("AUNI")
LUNI = common.be_word4("LUNI")
TUNI = common.be_word4("TUNI")

# Node creation
CREA = common.be_word4("CREA")
SLCT = common.be_word4("SLCT")
ATTR = common.be_word4("ATTR")

CONS = common.be_word4("CONS")
CONN = common.be_word4("CONN")

# Data types
FLGS = common.be_word4("FLGS")
DBLE = common.be_word4("DBLE")
DBL3 = common.be_word4("DBL3")
STR_ = common.be_word4("STR ")
FLT2 = common.be_word4("FLT2")
CMPD = common.be_word4("CMPD")
MESH = common.be_word4("MESH")
NRBC = common.be_word4("NRBC")


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


class MayaBinaryParser(iff.IffParser, common.MayaParserBase):
    def __init__(self, stream):
        # Determine Maya format based on magic number
        # Maya 2014+ files begin with a FOR8 block, indicating a 64-bit format.
        magic_number = stream.read(4)
        stream.seek(0)
        if magic_number == "FOR4":
            format = MAYA_BINARY_32
        elif magic_number == "FOR8":
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
                self.on_requires_maya(self._read_chunk_data(chunk))
            
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
                angle_unit = self._read_chunk_data(chunk)

            # currentUnit (linear)
            elif chunk.typeid == LUNI:
                linear_unit = self._read_chunk_data(chunk)

            # currentUnit (time)
            elif chunk.typeid == TUNI:
                time_unit = self._read_chunk_data(chunk)

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
            # Python 2 version. For Python 3 version see
            # https://github.com/DarkStarSword/3d-fixes/blob/master/unity_asset_extractor.py#L13
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
                if ord(b) >= ord(' ') and ord(b) <= ord('~'):
                    a += b
                else:
                    a += '.'
                ret += '%02X' % ord(b)
            if a:
                rem = width - (i % width) - 1
                ret += ' ' * (rem*2)
                ret += ' ' * (rem//4 + 1)
                ret += '| %s%s |\n' % (a, ' ' * rem)
            return ret

        print('CHUNK \"%s\"' % struct.pack('>I', chunk.typeid))
        start = 0
        if remaining:
            start = offset - chunk.data_offset
            print('        ...:')
        if hexdump:
            #print(codecs.encode(data, 'hex'))
            print _hexdump(data, start=start, indent=3),

    def _parse_node(self, mtypeid):
        for chunk in self._iter_chunks():
            # Create node
            if chunk.typeid == CREA:
                typename = self.__mtypeid_to_typename.get(mtypeid, "unknown")
                name_parts = self._read_chunk_data(chunk)[1:-1].split("\0")
                name = name_parts[0]
                parent_name = name_parts[1] if len(name_parts) > 1 else None
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
        #self._dump_chunk(chunk)
        attr_name, count = self._parse_attribute_info()

        # Making heavy use of asserts to catch any variants I haven't seen so I can
        # make sure they are parsed correctly rather than risking passing garbage out
        assert(count == 1)

        def struct_read(format):
            return struct.unpack(format, self.stream.read(struct.calcsize(format)))

        # "degree" and "order" are guesses
        u0, degree, u2, u3, order, u5, u6, u7 = struct_read(">2I5s4If")
        print('            Degree?: %i' % degree)
        print('             Order?: %i' % order)

        assert u0 == 1, u0
        assert degree >= 1, degree
        assert u2 == '\0'*5, u2 # 5 bytes messes up 32bit alignment here
        assert u3 == 3, u3
        assert order == degree + 1, (order, degree)
        assert u5 == 0, u5
        assert u6 == 0, u6
        assert u7 == 1.875, u7

        #self._dump_chunk(chunk, remaining=True)

        for i in range(degree - 1):
            u8, u9 = struct_read(">2I")
            print('    not... knot? %2i: %08x' % (i, u9))
            assert u8 == 0, u8
        u8a, u9a = struct_read(">2I")
        assert u8a == 0, u8a
        assert u9a == order, u9a

        for i in range(order):
            x, u10, y, u11, z, u12 = struct_read(">fIfIfI")
            print('   control point %2i: %9f %9f %9f' % (i, x, y, z))
            print( '                      %08x  %08x  %08x' % (u10, u11, u12)) # ???
            # Noticed a few cases where u11 appears to increment by one between
            # points & curves. Possibly an ID, but other times it remains fixed
            # for several points or changes randomly.

        assert(self._get_offset() == chunk.data_offset + chunk.data_length)

        self.on_set_attr(attr_name, None, type="NRBC")

    def _parse_mpxdata_attribute(self, typeid):
        # TODO
        pass

    def _load_mtypeid_database(self, path):
        with open(path) as f:
            line = f.readline()
            while line:
                mtypeid = common.be_word4(line[:4])
                typename = line[5:].strip()
                self.__mtypeid_to_typename[mtypeid] = typename
                line = f.readline()
