from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import re
import threading
import uuid

from ..core.brain import Brain
from ..errors import NKBError
from ..storage.jsonfile import JsonFileStorage
from ..utils import now

try:
    import fcntl
except ImportError:  # Windows callers still share the process lock.
    fcntl = None

_PROCESS_LOCK = threading.RLock()
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class LibraryError(NKBError, ValueError):
    pass


class LibraryManager:
    """每个库独立 Brain 文件，注册表只存名称与位置，不共享profile或对话。

    初始化只把已有 legacy_path 映射为 default，绝不覆写或搬移旧库。
    调用方可缓存 open() 返回的 Brain，并按库持有操作锁与保存责任。
    """

    def __init__(self, data_dir: str | Path, legacy_path: str | Path | None = None):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory = self.root / "libraries"
        self.directory.mkdir(exist_ok=True, mode=0o700)
        self.legacy_path = Path(legacy_path).expanduser().resolve() if legacy_path else self.root / "personal.brain.json"
        self.registry_path = self.root / "libraries.json"
        self._storage = JsonFileStorage(self.registry_path)
        with self._locked():
            if not self.registry_path.exists():
                entry = {"id": "default", "name": "默认记忆库", "is_demo": False,
                         "created": now(), "storage": "legacy" if self.legacy_path.exists() else "managed"}
                if entry["storage"] == "managed":
                    path = self.directory / "default.brain.json"
                    if path.exists():
                        raise LibraryError("发现未注册的默认库文件，已保留；请先恢复注册表")
                    Brain.new(path, name=entry["name"]).save()
                self._storage.save({"version": 1, "default_id": "default", "selected_id": "default",
                                    "libraries": {"default": entry}, "trash": {}})
            self._load()

    @contextmanager
    def _locked(self):
        with _PROCESS_LOCK:
            with (self.root / ".libraries.lock").open("a+b") as lock:
                if fcntl:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise LibraryError("记忆库ID格式不正确，不能包含路径或特殊字符")
        return value

    def _load(self):
        data = self._storage.load()
        if data.get("version") != 1 or not isinstance(data.get("libraries"), dict):
            raise LibraryError("记忆库注册表格式不正确，已保留原文件")
        trash=data.setdefault("trash",{})
        if not isinstance(trash,dict) or set(trash)&set(data["libraries"]):
            raise LibraryError("记忆库回收站注册项不正确")
        for collection in (data["libraries"],trash):
            for key, entry in collection.items():
                self._id(key)
                if (not isinstance(entry, dict) or entry.get("id") != key
                        or entry.get("storage") not in ("managed", "legacy", "external_demo")
                        or not isinstance(entry.get("name"), str) or type(entry.get("is_demo")) is not bool):
                    raise LibraryError("记忆库注册项格式不正确")
                if entry["storage"] == "legacy" and key != "default":
                    raise LibraryError("只有default可以映射旧个人库")
                if entry["storage"] == "external_demo" and (key != "demo" or not entry.get("is_demo")):
                    raise LibraryError("外部示例库注册项不正确")
        if data.get("default_id") not in data["libraries"]:
            raise LibraryError("默认记忆库注册项缺失")
        if data["libraries"][data["default_id"]]["is_demo"]:
            raise LibraryError("示例库不能成为默认个人库")
        return data

    def _path(self, entry):
        if entry["storage"] == "legacy":
            return self.legacy_path
        if entry["storage"] == "external_demo":
            return Path(entry["path"]).expanduser().resolve()
        return self.directory / f"{self._id(entry['id'])}.brain.json"

    def _entry(self, data, library_id):
        library_id = self._id(data["default_id"] if library_id is None else library_id)
        if library_id not in data["libraries"]:
            raise LibraryError("记忆库不存在")
        return data["libraries"][library_id]

    def _public(self, entry):
        result = {key: deepcopy(entry[key]) for key in ("id", "name", "is_demo", "created")}
        result["read_only"] = bool(entry["is_demo"])
        try:
            raw = JsonFileStorage(self._path(entry)).load()
            result["node_count"] = len(raw["nodes"]) if isinstance(raw.get("nodes"), dict) else None
            result["raw_node_count"] = result["node_count"]
            result["duplicate_count"] = 0
            if result["node_count"]:
                from types import SimpleNamespace
                from ..companion.dedup import is_duplicate
                view=SimpleNamespace(nodes=raw["nodes"],meta=raw.get("meta") or {},get=raw["nodes"].get)
                result["duplicate_count"]=sum(is_duplicate(node,view) for node in raw["nodes"].values())
                result["node_count"]-=result["duplicate_count"]
            result["available"] = result["node_count"] is not None
        except (OSError, ValueError):
            result.update(node_count=None, available=False)
        return result

    @property
    def default_id(self):
        with self._locked():
            return self._load()["default_id"]

    @property
    def selected_id(self):
        with self._locked():
            data = self._load()
            return data.get("selected_id", data["default_id"])

    def select(self, library_id):
        with self._locked():
            data = self._load()
            entry = self._entry(data, library_id)
            data["selected_id"] = entry["id"]
            self._storage.save(data)
            return self._public(entry)

    def list_libraries(self):
        with self._locked():
            return [self._public(entry) for entry in self._load()["libraries"].values()]

    def get_library(self, library_id):
        with self._locked():
            return self._public(self._entry(self._load(), library_id))

    def path_for(self, library_id=None):
        with self._locked():
            return self._path(self._entry(self._load(), library_id))

    def open_library(self, library_id=None):
        with self._locked():
            entry = self._entry(self._load(), library_id)
            path = self._path(entry)
            if not path.is_file():
                raise LibraryError("记忆库文件缺失，未创建空文件替代，请恢复备份")
            brain = Brain.open(path)
            if entry["is_demo"]:
                brain.meta["demo"] = True
            return brain

    def create_library(self, name: str, library_id: str | None = None):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise LibraryError("库名必须是最多80字的非空字符串")
        try:
            name.encode("utf-8")
        except UnicodeError:
            raise LibraryError("库名包含无法保存的字符") from None
        library_id = self._id(library_id if library_id is not None else "lib_" + uuid.uuid4().hex)
        if library_id == "demo":
            raise LibraryError("demo为示例库保留ID")
        with self._locked():
            data = self._load()
            path = self.directory / f"{library_id}.brain.json"
            if library_id in data["libraries"] or library_id in data["trash"] or path.exists():
                raise LibraryError("记忆库ID已存在，未覆盖任何文件")
            entry = {"id": library_id, "name": name.strip(), "is_demo": False, "created": now(), "storage": "managed"}
            Brain.new(path, name=entry["name"]).save()
            data["libraries"][library_id] = entry
            self._storage.save(data)
            return self._public(entry)

    @property
    def demo_suppressed(self):
        """Startup code must check before seeding a demo file, not only registering it."""
        with self._locked():
            return "demo" in self._load()["trash"]

    @staticmethod
    def _trashed_public(item):
        # Storage paths stay private to the manager; callers only need identity/status.
        return {**item,"in_trash":True,"restorable":bool(item.get("available"))}

    def list_trash(self):
        with self._locked():
            rows=[]
            for entry in self._load()["trash"].values():
                rows.append(self._trashed_public({**self._public(entry),"deleted_at":entry["deleted_at"]}))
            return sorted(rows,key=lambda r:r["deleted_at"],reverse=True)

    def delete_library(self, library_id):
        """Move an identity into the reversible registry trash; no data file is removed.

        The owning controller must revoke connections/cancel jobs/close its cached
        graph before calling this. The manager never silently rebinds a connection.
        """
        with self._locked():
            data=self._load();library_id=self._id(library_id)
            if library_id in data["trash"]:
                entry=data["trash"][library_id]
                return {"deleted":True,"duplicate":True,"library":self._trashed_public({**self._public(entry),"deleted_at":entry["deleted_at"]}),
                        "default_id":data["default_id"],"selected_id":data.get("selected_id",data["default_id"]),"raw_files_removed":False}
            entry=deepcopy(self._entry(data,library_id));entry["deleted_at"]=now()
            data["libraries"].pop(library_id);data["trash"][library_id]=entry
            created=None
            if data["default_id"]==library_id:
                eligible=[item for item in data["libraries"].values() if not item["is_demo"] and self._public(item)["available"]]
                if eligible:
                    fallback=min(eligible,key=lambda item:(item["created"],item["id"]))
                else:
                    identity="lib_"+uuid.uuid4().hex
                    while identity in data["libraries"] or identity in data["trash"] or (self.directory/f"{identity}.brain.json").exists():
                        identity="lib_"+uuid.uuid4().hex
                    fallback={"id":identity,"name":"新的默认记忆库","is_demo":False,"created":now(),"storage":"managed"}
                    created=self._path(fallback)
                    Brain.new(created,name=fallback["name"]).save()
                    data["libraries"][identity]=fallback
                data["default_id"]=fallback["id"]
            if data.get("selected_id")==library_id or data.get("selected_id") not in data["libraries"]:
                data["selected_id"]=data["default_id"]
            try:self._storage.save(data)
            except Exception:
                # Only the brand-new empty fallback belongs to this failed attempt.
                # The deleted user's original file is never touched or moved.
                if created is not None:
                    try:created.unlink()
                    except OSError:pass
                raise
            return {"deleted":True,"duplicate":False,"library":self._trashed_public({**self._public(entry),"deleted_at":entry["deleted_at"]}),
                    "default_id":data["default_id"],"selected_id":data["selected_id"],
                    "fallback_created":created is not None,"raw_files_removed":False}

    def restore_library(self, library_id, *, select=True):
        """Restore the same identity, idle: organizer consent is never revived."""
        if type(select) is not bool:raise LibraryError("select必须是布尔值")
        with self._locked():
            data=self._load();library_id=self._id(library_id)
            if library_id not in data["trash"]:raise LibraryError("回收站中没有这个记忆库")
            entry=deepcopy(data["trash"][library_id]);path=self._path(entry)
            if not path.is_file():raise LibraryError("记忆库文件缺失，未用空库替代；请先找回原文件或备份")
            try:
                brain=Brain.open(path)
                profile=brain.meta.get("organizer_profile")
                if isinstance(profile,dict) and profile.get("enabled") is not False:
                    profile["enabled"]=False;brain.persist()
            except Exception as exc:
                raise LibraryError("记忆库暂时无法安全恢复，原文件和回收站记录均保留") from exc
            entry.pop("deleted_at",None)
            data["trash"].pop(library_id);data["libraries"][library_id]=entry
            if select:data["selected_id"]=library_id
            self._storage.save(data)
            return {"restored":True,"library":self._public(entry),"default_id":data["default_id"],
                    "selected_id":data.get("selected_id",data["default_id"]),"connections_rebound":False,
                    "organizer_enabled":False}

    def register_demo(self, path: str | Path, name: str = "框架示例"):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise LibraryError("示例库名必须是最多80字的非空字符串")
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise LibraryError("示例库文件不存在")
        if path == self.legacy_path or path.parent == self.directory:
            raise LibraryError("不能把个人库注册成示例库")
        with self._locked():
            data = self._load()
            if "demo" in data["trash"]:
                entry=data["trash"]["demo"]
                return {**self._trashed_public({**self._public(entry),"deleted_at":entry["deleted_at"]}),"registration_suppressed":True}
            old = data["libraries"].get("demo")
            if old and self._path(old) != path:
                raise LibraryError("已有不同示例库，请明确迁移配置")
            entry = {"id": "demo", "name": name, "is_demo": True, "created": old["created"] if old else now(),
                     "storage": "external_demo", "path": str(path)}
            data["libraries"]["demo"] = entry
            self._storage.save(data)
            return self._public(entry)

    create = create_library
    open = open_library
    list = list_libraries
    trash = delete_library
    restore = restore_library
