import pytest

from src.recon.platforms.registry import PlatformRegistry


class SearchOnly:
    platform_id = "douyin"

    def collect_search(self, request):
        raise AssertionError("本测试只验证能力注册")


def test_search_only_platform_does_not_need_fake_creator_or_detail_implementation():
    registry = PlatformRegistry()
    search = SearchOnly()
    registry.register_search_collector(search)

    assert registry.search_collector("douyin") is search
    with pytest.raises(ValueError, match="does not support creator feeds"):
        registry.creator_feed_collector("douyin")
    with pytest.raises(ValueError, match="does not support content details"):
        registry.content_detail_collector("douyin")
