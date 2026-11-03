# mini-count

统计一段文本里每个单词出现的次数，按次数从多到少打印。

## 规格

- `lib/tokenize.js` 的 `tokenize(text)` 返回小写单词数组：
  只保留 `[a-z0-9']`，撇号属于单词（`don't` 是一个词），其余标点丢弃，空串不返回。
- `lib/count.js` 的 `count(text)` 返回 `Map<word, count>`。
- `lib/count.js` 的 `top(counts, limit = 3)` 返回 `[word, count][]`：
  次数降序；**次数相同时按单词升序**；最多 `limit` 条。
- `bin/cli.js` 接受一个文件路径，每行打印 `word<TAB>count`，只打印 `top` 的结果。

## 现状

`node --test tests/visible/basic.test.mjs` 目前有三个失败：

1. `tokenize` 按空白切分，标点被当成单词的一部分，大小写也没统一。
2. `top` 只按次数排序，次数相同的单词顺序不稳定。

另外 `bin/cli.js` 只打印了单词，没有打印次数。

## 约束

- 只改 `lib/` 和 `bin/` 下的文件。
- 不新增依赖。
