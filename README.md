# png-codec

PNG 编解码（8 位 RGB / RGBA，逐行 filter、分块 CRC、IDAT 拼接），只用 Python 标准库。

```
python3 -m pngcodec.cli --sample mixed --out /tmp/mixed.png
python3 -m pngcodec.cli --info /tmp/mixed.png
python3 -m unittest discover -s tests -v
```

## 口径（README 为准）

- **分块 CRC 必须写对**：`--make 2x2 --out a.png` 之后 `--info a.png` 现在给 `crc=bad`（CRC 全写 0），
  按口径要 `crc=ok`，而且读取时要校验每个分块的 CRC，坏 CRC 要报错并给分块偏移。
- **五种 filter 都要支持**：`--sample mixed --out m.png`（每行分别用 0/1/2/3/4 号 filter）
  现在 `--pixels` 直接报「只支持 filter 0」，按口径要正确反过滤并打印像素。
- **IDAT 要按顺序拼接**：`--sample split --out s.png`（IDAT 拆成 4 块）现在只取第一块、解压必然失败，
  按口径要把所有 IDAT 拼起来再解压。
- 写入：filter 要按行自适应（每行选表内绝对增量最小的那种），单个 IDAT 的载荷上限 8192 字节，超出要拆分；
  IHDR 的位深与颜色类型必须写对。
- 不变量：`decode(encode(w, h, pixels))` 逐字节等于输入（RGB 与 RGBA 都要）；同一张图重复编码逐字节相同；
  写出的文件必须能被本工具自己读回，且 CRC 校验通过。
- 规模：100 MB 的原始像素单遍处理，内存 O(一行 + 一个分块)；不许把整张图展开成多层列表。

## 现在的行为

- `_chunk` 把 CRC 写成 `\x00\x00\x00\x00`，所以自己写出的文件 `crc=bad`。
- `decode` 只支持 `filter_type == 0`，其它 filter 一律报错。
- `decode` 里 `if not idat: idat = payload`：多块 IDAT 只留第一块。

## 计划新增的能力

```
--make WxH       生成测试图
--sample 名称    paeth / mixed / split 三种样本
--out 文件       输出文件
--info 文件      打印尺寸、位深、颜色类型、IDAT 块数与 CRC 结论
--pixels 文件    打印解码后的像素
```

## 输出

```
width=4 height=4 bit_depth=8 color_type=2 idat_chunks=1 crc=ok
row=0 hex=0000003753…
```

## 目录

```
pngcodec/png.py    编解码与分块
pngcodec/cli.py    命令行入口 + 参考实现（样本用）
tests/             unittest 用例
```
