"""Minimal protobuf definitions for the V2Ray stats gRPC service.

Generated-code-free: the descriptors are built at import time so the project
does not depend on a protoc toolchain.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

PACKAGE = "v2ray.core.app.stats.command"
SERVICE = f"/{PACKAGE}.StatsService/QueryStats"


def _build_messages():
    proto = descriptor_pb2.FileDescriptorProto()
    proto.name = "ostium_v2ray_stats.proto"
    proto.package = PACKAGE
    proto.syntax = "proto3"

    stat = proto.message_type.add()
    stat.name = "Stat"
    field = stat.field.add()
    field.name = "name"
    field.number = 1
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    field = stat.field.add()
    field.name = "value"
    field.number = 2
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_INT64

    request = proto.message_type.add()
    request.name = "QueryStatsRequest"
    field = request.field.add()
    field.name = "pattern"
    field.number = 1
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    field = request.field.add()
    field.name = "reset"
    field.number = 2
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL

    response = proto.message_type.add()
    response.name = "QueryStatsResponse"
    field = response.field.add()
    field.name = "stat"
    field.number = 1
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    field.type_name = f".{PACKAGE}.Stat"

    pool = descriptor_pool.DescriptorPool()
    pool.Add(proto)
    stat_class = message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{PACKAGE}.Stat"))
    request_class = message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{PACKAGE}.QueryStatsRequest"))
    response_class = message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{PACKAGE}.QueryStatsResponse"))
    return stat_class, request_class, response_class


Stat, QueryStatsRequest, QueryStatsResponse = _build_messages()

__all__ = ["SERVICE", "QueryStatsRequest", "QueryStatsResponse", "Stat"]
