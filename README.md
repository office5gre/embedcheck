# embedcheck

**核对向量库里的内容与来源是否还对得上。**

`embedcheck` —— 比对向量库中的条目与来源文件，标出内容已变、已删或重复入库的条目。

- 零依赖，Python 3.10+ 标准库即可运行
- 单文件，`embedcheck.py` 拷走就能用
- 不联网、不写文件

<!-- ipos:install -->
## 安装

零依赖，Python 3.10+ 即可：

```bash
pip install office5gre-embedcheck
```

装完直接用命令名调用：

```bash
embedcheck --help
```

也可以不用安装，直接把 `embedcheck.py` 拷走用——它只依赖标准库。

## 为什么需要它

向量库工具多只管写入；embedcheck 核对库里的内容与来源现状，抓出「文档改了但向量还是旧的」。

它遵守下面几条自己定的规矩：

1. **文档改了，向量库不会自己知道**。所以要拿库里的条目去比对来源现状。
2. **只说「该更新哪些」，不重建索引**。重建是另一件事，风险也更大。
3. **分清三种情况**：内容变了、来源没了、重复入库。三者的处理完全不同。

## 用法

```bash
python embedcheck.py --store store.jsonl --source ./docs
python embedcheck.py --store store.jsonl --source ./docs --json
```

加 `--json` 可以拿到机器可读的结果，便于接到流水线里。

## 已知局限

- 相似度用字符集合估算，不等于向量余弦相似度。
- 只说「该更新哪些」，不重建索引。
- 来源目录与库里的路径写法不一致时，靠归一化匹配，可能误配。

## 跑测试

```bash
python test_embedcheck.py
```

测试用独立的断言与临时数据，不污染工作目录。

## 来源与参考

- Python 标准库文档：<https://docs.python.org/3/>
- GitHub 仓库：<https://github.com/office5gre/embedcheck>

---

## 关于作者

office5gre 做向量索引与来源的同步相关的问题。这个工具先替你回答一个具体问题，再谈别的。

- 个人主页：<https://office5gre.github.io>
- 仓库：<https://github.com/office5gre/embedcheck>

## 许可

MIT，见 [LICENSE](LICENSE)。
