"""Parquet 常用操作封装 —— 读写、分区、合并、Schema 管理。

基于 pandas + pyarrow/fastparquet 引擎，提供高效列式存储的日常操作。

函数                                   用途
──────────────────────────────────────────────────────────────────
read_parquet(path)                      读取单个 parquet 文件，返回 DataFrame
write_parquet(df, path)                 写入单个 parquet 文件
read_partitioned(base_dir)              读取按目录分区的 parquet 数据集
write_partitioned(df, base_dir, keys)   按列值分目录写入分区数据集
read_schema(path)                       查看 parquet 文件的 schema（列名与类型）
merge_parquet(input_dir, output_path)   将目录下所有 parquet 合并为单个文件
append_parquet(df, path)                追加写入已存在的 parquet 文件
get_metadata(path)                      获取 parquet 文件的元信息（行数、列数等）
scan_columns(path, columns)             只读取指定列（列裁剪，减少内存占用）
"""

import os
from pathlib import Path
from typing import Any

import pandas as pd


def read_parquet(path: str, *, columns: list[str] | None = None) -> pd.DataFrame:
    """读取单个 parquet 文件，返回 DataFrame。

    Args:
        path: parquet 文件路径
        columns: 仅读取指定列，传 None 表示读取所有列
    """
    return pd.read_parquet(path, columns=columns)


def write_parquet(
    df: pd.DataFrame,
    path: str,
    *,
    compression: str = "snappy",
    index: bool = False,
) -> None:
    """将 DataFrame 写入单个 parquet 文件。

    Args:
        df: 要写入的 DataFrame
        path: 输出文件路径，父目录不存在时自动创建
        compression: 压缩算法 (snappy / gzip / brotli / zstd / none)
        index: 是否保留 DataFrame 的 index 列
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    df.to_parquet(path, compression=compression, index=index)


def read_partitioned(base_dir: str, *, filters: list[tuple] | None = None) -> pd.DataFrame:
    """读取按目录分区的 parquet 数据集。

    分区目录结构示例：base_dir/date=2024-01-01/data.parquet

    Args:
        base_dir: 分区根目录
        filters: pyarrow 风格的过滤条件，如 [("date", "=", "2024-01-01")]
    """
    return pd.read_parquet(base_dir, filters=filters)


def write_partitioned(
    df: pd.DataFrame,
    base_dir: str,
    partition_keys: list[str],
    *,
    compression: str = "snappy",
    index: bool = False,
) -> None:
    """按列值分目录写入分区 parquet 数据集。

    写入后的目录结构：base_dir/key1=value1/key2=value2/data.parquet

    Args:
        df: 要写入的 DataFrame，必须包含 partition_keys 中的列
        base_dir: 分区根目录
        partition_keys: 分区列名列表
        compression: 压缩算法
        index: 是否保留 DataFrame 的 index 列
    """
    os.makedirs(base_dir, exist_ok=True)
    # 使用 to_parquet 的分区能力
    df.to_parquet(
        base_dir,
        partition_cols=partition_keys,
        compression=compression,
        index=index,
    )


def read_schema(path: str) -> pd.DataFrame:
    """查看 parquet 文件的 schema（列名与数据类型）。

    Args:
        path: parquet 文件路径

    Returns:
        包含 column 和 type 两列的 DataFrame
    """
    schema = pd.read_parquet(path).dtypes.reset_index()
    schema.columns = ["column", "type"]
    return schema


def merge_parquet(input_dir: str, output_path: str, *, pattern: str = "*.parquet") -> None:
    """将目录下所有 parquet 文件合并为单个文件。

    Args:
        input_dir: 包含 parquet 文件的目录
        output_path: 合并后的输出路径
        pattern: 匹配 parquet 文件的 glob pattern
    """
    files = sorted(Path(input_dir).rglob(pattern))
    if not files:
        raise FileNotFoundError(f"在 {input_dir} 中未找到匹配 {pattern} 的 parquet 文件")
    dfs = [pd.read_parquet(str(f)) for f in files]
    merged = pd.concat(dfs, ignore_index=True)
    write_parquet(merged, output_path)


def append_parquet(df: pd.DataFrame, path: str) -> None:
    """追加写入已存在的 parquet 文件。

    如果文件不存在，则创建新文件；如果文件存在，则读取后拼接再写入。

    Args:
        df: 要追加的 DataFrame，列结构需与已有数据一致
        path: 目标文件路径
    """
    if os.path.exists(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
    write_parquet(df, path)


def get_metadata(path: str) -> dict[str, Any]:
    """获取 parquet 文件的元信息。

    Args:
        path: parquet 文件路径

    Returns:
        包含 num_rows, num_columns, columns, size_mb 等信息的字典
    """
    df = pd.read_parquet(path)
    file_size = os.path.getsize(path)
    return {
        "num_rows": len(df),
        "num_columns": len(df.columns),
        "columns": df.columns.tolist(),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "size_mb": round(file_size / 1024 / 1024, 4),
    }


def scan_columns(path: str, columns: list[str]) -> pd.DataFrame:
    """只读取指定列（列裁剪优化，减少内存占用）。

    Args:
        path: parquet 文件路径
        columns: 需要的列名列表
    """
    return pd.read_parquet(path, columns=columns)
