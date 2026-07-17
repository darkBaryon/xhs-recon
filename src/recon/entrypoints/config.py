from dataclasses import dataclass
from pathlib import Path

import yaml

from ..domain.content import AccountTarget
from ..platforms.xhs.collector import normalize_xhs_target
from .config_models import RunConfig


@dataclass(frozen=True, slots=True)
class LoadedAccountConfig:
    run: RunConfig
    targets: tuple[AccountTarget, ...]


@dataclass(frozen=True, slots=True)
class LoadedSearchConfig:
    run: RunConfig
    keywords: tuple[str, ...]
    synonyms: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class LoadedWatchlistConfig:
    run: RunConfig
    targets: tuple[AccountTarget, ...]


def _read_asset_yaml(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        raise ValueError(f"引用的资产文件不存在：{path_str}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"资产文件顶层须为键值映射：{path_str}")
    return data


def resolve_config_refs(config: dict) -> dict:
    keywords_file = config.get("keywords_file")
    if keywords_file:
        if "keywords" in config or "synonyms" in config:
            raise ValueError("keywords_file 与主配置 keywords/synonyms 不可同时提供，二选一")
        data = _read_asset_yaml(keywords_file)
        if "keywords" not in data:
            raise ValueError(f"keywords_file 缺少 keywords 键：{keywords_file}")
        config["keywords"] = data["keywords"]
        if "synonyms" in data:
            config["synonyms"] = data["synonyms"]

    watchlist_file = config.get("watchlist_file")
    if watchlist_file:
        watchlist = config.get("watchlist") or {}
        if watchlist.get("manual"):
            raise ValueError("watchlist_file 与主配置 watchlist.manual 不可同时提供，二选一")
        data = _read_asset_yaml(watchlist_file)
        if "manual" not in data:
            raise ValueError(f"watchlist_file 缺少 manual 键：{watchlist_file}")
        watchlist["manual"] = data["manual"]
        config["watchlist"] = watchlist

    account_file = config.get("account_analysis_file")
    if account_file:
        account = config.get("account_analysis") or {}
        if account.get("accounts"):
            raise ValueError(
                "account_analysis_file 与主配置 account_analysis.accounts 不可同时提供，二选一"
            )
        data = _read_asset_yaml(account_file)
        if "accounts" not in data:
            raise ValueError(f"account_analysis_file 缺少 accounts 键：{account_file}")
        account["accounts"] = data["accounts"]
        config["account_analysis"] = account
    return config


def _target(entry) -> AccountTarget:
    if isinstance(entry, str):
        return AccountTarget(normalize_xhs_target(entry))
    if isinstance(entry, dict):
        ref = entry.get("account_id") or entry.get("id") or entry.get("url") or entry.get("ref")
        if not ref:
            raise ValueError(f"account_analysis.accounts 条目缺少 account_id/id/url/ref：{entry}")
        nickname = str(entry.get("nickname") or entry.get("name") or "").strip()
        source = "self" if entry.get("self") or entry.get("owner") else "manual"
        return AccountTarget(normalize_xhs_target(str(ref)), nickname, source)
    raise ValueError(f"invalid account analysis target: {entry}")


def load_run_config(path: str) -> RunConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"配置文件不存在：{path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"配置顶层须为键值映射：{path}")
    return RunConfig.model_validate(resolve_config_refs(raw))


def load_account_config(path: str) -> LoadedAccountConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"配置文件不存在：{path}")
    run = load_run_config(path)
    if run.account_analysis is None or not run.account_analysis.accounts:
        raise ValueError("请配置 account_analysis_file 或 account_analysis.accounts")
    if run.account_analysis.incremental:
        raise ValueError("account_analysis.incremental 尚未实现；期1请使用全量模式")
    return LoadedAccountConfig(
        run=run,
        targets=tuple(_target(entry) for entry in run.account_analysis.accounts),
    )


def load_search_config(path: str) -> LoadedSearchConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"配置文件不存在：{path}")
    run = load_run_config(path)
    keywords = tuple(keyword.strip() for keyword in run.keywords if keyword.strip())
    if not keywords:
        raise ValueError("请配置 keywords_file 或 keywords")
    allowed_sorts = {"", "general", "popularity_descending", "time_descending"}
    if run.search.sort not in allowed_sorts:
        raise ValueError(f"不支持的 search.sort：{run.search.sort}")
    synonyms = {
        seed: tuple(term for term in terms if term.strip())
        for seed, terms in (run.synonyms or {}).items()
    }
    return LoadedSearchConfig(run=run, keywords=keywords, synonyms=synonyms)


def load_watchlist_config(path: str) -> LoadedWatchlistConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"配置文件不存在：{path}")
    run = load_run_config(path)
    if run.watchlist is None or not run.watchlist.manual:
        raise ValueError("请配置 watchlist_file 或 watchlist.manual")
    targets = tuple(_target(entry) for entry in run.watchlist.manual)
    if run.watchlist.max_total > 0:
        targets = targets[: run.watchlist.max_total]
    return LoadedWatchlistConfig(run=run, targets=targets)
