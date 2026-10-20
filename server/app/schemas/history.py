"""历史区间查询 DTO（M8，契约 §4.2 / 03 §2.10）。

点结构为 [epoch 毫秒, 工程值数值]（服务端换算流水后；boolean 存 1/0），
序列按 ts 升序；series 的键为变量 key（缺省 keys 时为区间内有数据的全部 key）。
"""
from pydantic import BaseModel, Field


class HistoryResponse(BaseModel):
    series: dict[str, list[list[float]]] = Field(default_factory=dict)
