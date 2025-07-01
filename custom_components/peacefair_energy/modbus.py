import logging
import asyncio
from pymodbus.client import ModbusTcpClient, ModbusUdpClient
from pymodbus.transaction import ModbusRtuFramer, ModbusIOException
from pymodbus.pdu import ModbusRequest
import threading
try:
    from homeassistant.const import (
        SensorDeviceClass
    )

except ImportError:
    SensorDeviceClass.VOLTAGE = "voltage"
    SensorDeviceClass.CURRENT = "current"
    SensorDeviceClass.POWER = "power"
    SensorDeviceClass.ENERGY = "energy"
    SensorDeviceClass.POWER_FACTOR = "power_factor"
    SensorDeviceClass.FREQUENCY = "Power Frequency"

HPG_SENSOR_TYPES = [
    SensorDeviceClass.VOLTAGE ,
    SensorDeviceClass.CURRENT,
    SensorDeviceClass.POWER,
    SensorDeviceClass.ENERGY,
    SensorDeviceClass.POWER_FACTOR,
    SensorDeviceClass.FREQUENCY
]

_LOGGER = logging.getLogger(__name__)

class ModbusResetEnergyRequest(ModbusRequest):
    _rtu_frame_size = 4
    function_code = 0x42
    def __init__(self, **kwargs):
        ModbusRequest.__init__(self, **kwargs)

    def encode(self):
        return b''

    def get_response_pdu_size(self):
        return 4

    def __str__(self):
        return "ModbusResetEnergyRequest"

class ModbusHub:
    def __init__(self, protocol, host, port, slave):
        self._lock = threading.Lock()
        self._slave = slave
        if(protocol == "rtuovertcp"):
            self._client = ModbusTcpClient(
                host = host,
                port = port,
                framer = ModbusRtuFramer,
                timeout = 2,
                retry_on_empty = True,
                retry_on_invalid = False
            )
        elif (protocol == "rtuoverudp"):
            self._client = ModbusUdpClient(
                host = host,
                port = port,
                framer = ModbusRtuFramer,
                timeout = 2,
                retry_on_empty = False,
                retry_on_invalid = False
            )
            
    def connect(self):
        with self._lock:
            self._client.connect()

    def close(self):
        with self._lock:
            self._client.close()

#    def read_holding_register(self):
#        pass

    # 新增同步版本，供线程池调用
    def read_input_registers_sync(self, address, count):
        with self._lock:
            kwargs = {"slave": self._slave}
            return self._client.read_input_registers(address, count, **kwargs)

    # 异步版本，交给线程池执行，避免阻塞事件循环
    async def read_input_registers(self, address, count):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self.read_input_registers_sync,
            address,
            count
        )
    
    def reset_energy(self):
        with self._lock:
            kwargs = {"slave": self._slave}
            request = ModbusResetEnergyRequest(**kwargs)
            self._client.execute(request)

    # 异步版本info_gather
    async def info_gather(self):
        data = {}
        try:
            result = await self.read_input_registers(0, 9)
            if result is not None and type(result) is not ModbusIOException \
                    and result.registers is not None and len(result.registers) == 9:
                data[SensorDeviceClass.VOLTAGE] = result.registers[0] / 10
                data[SensorDeviceClass.CURRENT] = ((result.registers[2] << 16) + result.registers[1]) / 1000
                data[SensorDeviceClass.POWER] = ((result.registers[4] << 16) + result.registers[3]) / 10
                data[SensorDeviceClass.ENERGY] = ((result.registers[6] << 16) + result.registers[5]) / 1000
                data[SensorDeviceClass.FREQUENCY] = result.registers[7] / 10
                data[SensorDeviceClass.POWER_FACTOR] = result.registers[8] / 100
            else:
                _LOGGER.debug(f"Error in gathering, timed out")
        except Exception as e:
            _LOGGER.error(f"Error in gathering, {e}")
        return data
    
    # 如果有别的同步读写函数，也建议用类似方式异步包装