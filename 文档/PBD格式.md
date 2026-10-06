# PBD 支持范围与来源

当前读取器支持已验证的 LimeLightLemonadeJam `TJS/4s0` 样本，不代表支持所有 PBD 变体。源码入口为 `pbd_codec.py` 和 `pbd_parser.py`。

读取器只读原文件。文件上限 16 MiB，解压输出上限 64 MiB；未知模式、截断数据、越界引用和不支持的值类型会返回错误。PNG 图层按文件名主体、下划线和图层编号关联。

算法参考 BLAKE2、xxHash、LZ4 规格和 ChaCha8 公开测试向量；xp3-brute 0.3.7 的格式描述用于交叉核对，未作为运行依赖引入。

历史读取器来自 YeLikesss/KrkrPbdStandViewer，采用 AGPL-3.0。研究过程曾接触该实现，不能宣称严格净室。历史授权保持不变，当前入口没有旧实现回退。

- [BLAKE2](https://www.rfc-editor.org/rfc/rfc7693)
- [xxHash](https://github.com/Cyan4973/xxHash/blob/dev/doc/xxhash_spec.md)
- [LZ4](https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md)
- [ChaCha 测试向量](https://github.com/weidai11/cryptopp/blob/master/TestVectors/chacha.txt)
- [xp3-brute 0.3.7](https://crates.io/crates/xp3-brute/0.3.7)
- [历史读取器](https://github.com/YeLikesss/KrkrPbdStandViewer)
