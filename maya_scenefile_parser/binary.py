import os
import sys
import struct

from . import common, iff

if sys.version_info < (3, 0):
    def makeBytes(data):
        return bytes(data)
else:
    def makeBytes(data):
        return bytes(data, 'utf8')

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
    def __init__(self, stream, info_only=False):
        # Determine Maya format based on magic number
        # Maya 2014+ files begin with a FOR8 block, indicating a 64-bit format.
        self.info_only = info_only
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
            elif self.info_only:
                return
            elif mtypeid == FREF:
                self._parse_file_reference()
            elif mtypeid == CONN:
                self._parse_connection()
            else:
                self._parse_node(mtypeid)

        elif chunk.typeid == self.__list_chunk_type and not self.info_only:
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

    def _parse_node(self, mtypeid):
        for chunk in self._iter_chunks():
            # Create node
            if chunk.typeid == CREA:
                typename = self.__mtypeid_to_typename.get(mtypeid, "unknown")
                name_parts = self._read_chunk_data(chunk)[1:-1].split(b"\0")
                name = name_parts[0]
                parent_name = name_parts[1] if len(name_parts) > 1 else None
                self.on_create_node(typename, name, parent=parent_name)

            # Select the current node
            elif chunk.typeid == SLCT:
                pass

            # Dynamic attribute
            elif chunk.typeid == ATTR:
                pass

            # Flags
            elif chunk.typeid == FLGS:
                pass

            # Set attribute
            else:
                self._parse_attribute(chunk.typeid)

    def _parse_attribute(self, mtypeid):
        # TODO Support more primitive types
        if mtypeid == STR_:
            self._parse_string_attribute()
        elif mtypeid == DBLE:
            self._parse_double_attribute()
        elif mtypeid == DBL3:
            self._parse_double3_attribute()
        else:
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

    def _parse_mpxdata_attribute(self, tyepid):
        # TODO
        pass

    def _load_mtypeid_database(self, path):
        with open(path) as f:
            line = f.readline()
            while line:
                mtypeid = common.be_word4(makeBytes(line[:4]))
                typename = line[5:].strip()
                self.__mtypeid_to_typename[mtypeid] = typename
                line = f.readline()
