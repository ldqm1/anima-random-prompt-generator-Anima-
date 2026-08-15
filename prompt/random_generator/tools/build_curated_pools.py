"""独立脚本：重建 curated pools 并输出统计信息。

用法:
    python -m prompt.random_generator.tools.build_curated_pools
"""

from __future__ import annotations

from .. import config, retrieval


def main() -> int:
    """加载数据库、重建 pools、打印统计。"""
    database = retrieval.load_tag_database(config.TAG_SOURCE_FILE)
    artist_blacklist = retrieval.build_artist_blacklist(
        config.ARTIST_BLACKLIST_FILES[0],
        config.ARTIST_BLACKLIST_FILES[1],
    )

    pools = retrieval.build_curated_pools(
        database,
        top_n=500,
        blacklist=artist_blacklist,
        output_path=config.CURATED_POOLS_FILE,
    )

    print("原始数据库规模:")
    for category, tags in database.items():
        print(f"  {category}: {len(tags)}")

    print("\nCurated pool 规模:")
    for category, tags in pools.items():
        print(f"  {category}: {len(tags)}")

    print(f"\n已保存到 {config.CURATED_POOLS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
