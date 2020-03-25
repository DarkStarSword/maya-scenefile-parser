#!/usr/bin/env python

from maya_scenefile_parser import MayaAsciiParser, MayaBinaryParser
import sys, os

nodes = dict()

def parse(path):
    ext = os.path.splitext(path)[1]
    try:
        Base, mode = {
            ".ma": (MayaAsciiParser, "r"),
            ".mb": (MayaBinaryParser, "rb"),
        }[ext]
    except KeyError:
        raise RuntimeError("Invalid maya file: %s" % path)

    class Parser(Base):
        #def on_create_node(self, nodetype, name, parent):
        #    print('create_node', nodetype, name, parent)
        #    self.current_node = (name, parent, nodetype)

        #def on_set_attr(self, name, value, type):
        #    print('set_attr', name, value, type)
        #    if name not in ("nts", "notes"):
        #        return

        #    if self.current_node not in nodes:
        #        nodes[self.current_node] = {}

        #    nodes[self.current_node][name] = value

        #    print("{name} = {value} ({type})".format(**locals()))

        def on_requires_maya(self, version):
            print "Maya Version: %s" % version

        def on_requires_plugin(self, plugin, version):
            print "Requires Plugin: %s %s" % (plugin, version)

        def on_file_info(self, key, value):
            print "File Info [%16s]: %s" % (key, value)

        def on_current_unit(self, angle, linear, time):
            print "Units: Angle=%s Linear=%s Time=%s" % (angle, linear, time)

        def on_file_reference(self, path):
            print "Reference: %s" % path

        def on_create_node(self, nodetype, name, parent):
            print "Create Node: Type=%s Name=%s Parent=%s" % (nodetype, name, parent)

        def on_set_attr(self, name, value, type):
            print "Set Attribute: [%s] %s=%s" % (type, name, repr(value))

        def on_connect_attr(self, src, dst):
            print "Connect Attributes: %s => %s" % (src, dst)

    with open(path, mode) as f:
        parser = Parser(f)
        parser.parse()

    for node, attrs in nodes.iteritems():
        for key, value in attrs.iteritems():
            print("{node}.{key} = {value}".format(**locals()))

if __name__ == '__main__':
    for path in sys.argv[1:]:
        parse(path)
