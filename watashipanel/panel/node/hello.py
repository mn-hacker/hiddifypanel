# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
import grpc

# from watashipanel.hasync.config import BoolConfig 
from watashipanel.models.config import hconfig
from watashipanel.models.config_enum import ConfigEnum
from . import test_pb2
from . import test_pb2_grpc

class HelloServicer(test_pb2_grpc.HelloServicer):
    """Missing associated documentation comment in .proto file."""

    def SayHello(self, request: test_pb2.HelloRequest, context) -> test_pb2.HelloResponse:
            
            return test_pb2.HelloResponse(res=hconfig(ConfigEnum.log_level))
