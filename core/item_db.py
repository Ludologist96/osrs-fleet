import json
import os
import sqlite3
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any, List
from core.logger import get_logger
from PIL import Image
from io import BytesIO
import base64
from core import tools
from core import ocr
from core.logger import get_logger

_DC_SLOTS = {"slots": True} if sys.version_info >= (3, 10) else {}


@dataclass(**_DC_SLOTS)
class Item:
    """
    Represents an in-game item with its attributes.
    """
    id: int
    name: str
    tradeable_on_ge: bool
    members: bool
    noted: bool
    noteable: bool
    placeholder: bool
    stackable: bool
    equipable: bool
    cost: int
    lowalch: int
    highalch: int
    # The icon is loaded from the icon cache the first time it is used (only a few
    # items per bot), not for all ~43k items at start - that kept ~100+ MB per process.
    _icon: Optional[str] = field(default=None, repr=False, compare=False)
    _icon_loaded: bool = field(default=False, repr=False, compare=False)

    @property
    def icon_b64(self) -> Optional[str]:
        if not self._icon_loaded:
            self._icon = IconStore.get().cropped(self.id)
            self._icon_loaded = True
        return self._icon

    @property
    def icon(self) -> Image.Image:
        """
        Returns the icon image of the item.
        """
        if self.icon_b64:
            return Image.open(BytesIO(base64.b64decode(self.icon_b64)))
        return None

    @property
    def log(self):
        return get_logger('Item')
    
    def get_count(self, item_match: tools.MatchResult, sc: Image.Image) -> int:
        """
        Extracts and returns the item count from the provided screenshot and match area.
        """
        center = item_match.get_center()

        match = tools.MatchResult(
            start_x=center[0]-14,
            start_y=center[1]-30,
            end_x=center[0]+25,
            end_y=center[1]-5
        )
        #match.debug_draw(sc).show()
        
        scc = match.crop_in(sc)
        num_img = tools.mask_colors(scc, [
            (255, 255, 0), # < 100k
            # TODO: actually handle these
            # (255,255,255), # > 100k
            # (0, 255, 128)  # > 10M
        ], tolerance=5)

        try:
            return ocr.get_number(
                num_img,
                ocr.FontChoice.RUNESCAPE_PLAIN_11,
            )
        except Exception as e:
            self.log.error(f'Failed to get count for item: {self.name} - {str(e)}')
            match.debug_draw(sc).show()
            return 0

ICONS_JSON = Path("data/items/icons-items-complete.json")


class IconStore:
    """Item icons in a small SQLite file next to the JSON (or in $OSRS_CACHE_DIR), built
    once from icons-items-complete.json. A lookup reads one row, so a process holds only
    the icons it actually uses."""
    _instance: "IconStore | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "IconStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = IconStore()
            return cls._instance

    def __init__(self):
        cache_dir = Path(os.environ.get("OSRS_CACHE_DIR") or ICONS_JSON.parent)
        self.path = cache_dir / "icons.sqlite"
        self._local = threading.local()
        self._ensure()

    def _ensure(self):
        try:
            if self.path.exists() and self.path.stat().st_mtime >= ICONS_JSON.stat().st_mtime:
                return
        except OSError:
            pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        with open(ICONS_JSON, "r") as f:
            icons = json.load(f)
        con = sqlite3.connect(tmp)
        con.execute("CREATE TABLE icons (id INTEGER PRIMARY KEY, b64 TEXT)")
        con.executemany("INSERT INTO icons VALUES (?, ?)",
                        ((int(k), v) for k, v in icons.items() if v and k.isdigit()))
        con.commit()
        con.close()
        del icons
        os.replace(tmp, self.path)   # atomic: several processes may build at once
        try:
            os.chmod(self.path, 0o664)
        except OSError:
            pass

    def _con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            self._local.con = con
        return con

    def raw(self, item_id: int) -> Optional[str]:
        row = self._con().execute("SELECT b64 FROM icons WHERE id = ?", (item_id,)).fetchone()
        return row[0] if row else None

    def cropped(self, item_id: int) -> Optional[str]:
        b64 = self.raw(item_id)
        if not b64:
            return None
        from core.tools import base64_to_image, crop_transparent_border, image_to_base64
        try:
            return image_to_base64(crop_transparent_border(base64_to_image(b64)), fmt="PNG")
        except Exception:
            return b64



class ItemLookup:
    """
    Singleton class for looking up items in the OSRS database.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ItemLookup, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_items_by_id"):
            self.log = get_logger('ItemLookup')
            self.log.info("Initializing ItemLookup...")
            self._items_by_id: Dict[int, Item] = {}
            self._items_by_name: Dict[str, Item] = {}
            self._load_data()
            self.log.info(f"Loaded {len(self._items_by_id)} items into cache.")

    def _load_data(self):
        """
        Loads data from JSON files, filters out duplicates, populates the item cache,
        and synthesizes noted variants from canonicals (upstream cache only ships
        canonical entries; noted lookups need an entry per linked_id_noted).
        """
        try:
            with open("data/items/items-cache-data.json", "r") as f:
                items_data = json.load(f)

            # Pass 1: load canonicals
            for item in items_data.values():
                # Filter out duplicates: only include items with linked_id_item=None and linked_id_placeholder!=None
                if (item["linked_id_item"] is None and item["linked_id_placeholder"] is not None) or item["id"] not in self._items_by_id.keys():
                    item_obj = Item(
                        id=item["id"],
                        name=item["name"],
                        tradeable_on_ge=item["tradeable_on_ge"],
                        members=item["members"],
                        noted=item["noted"],
                        noteable=item["noteable"],
                        placeholder=item["placeholder"],
                        stackable=item["stackable"],
                        equipable=item["equipable"],
                        cost=item["cost"],
                        lowalch=item["lowalch"],
                        highalch=item["highalch"],
                    )

                    # Populate lookup dictionaries
                    self._items_by_id[item_obj.id] = item_obj
                    self._items_by_name[item_obj.name.lower()] = item_obj

            # Pass 2: synthesize noted variants from canonicals.
            # Upstream cache (DayV-git/osrsreboxed-db) ships only canonicals; noted variants
            # were previously hand-baked into the cache file. Deriving them here keeps the
            # cache file in sync with upstream without manual augmentation.
            # Noted ids are looked up by id only (name lookups still resolve to canonical).
            for raw in list(items_data.values()):
                noted_id = raw.get("linked_id_noted")
                if noted_id is None or noted_id in self._items_by_id:
                    continue
                self._items_by_id[noted_id] = Item(
                    id=noted_id,
                    name=raw["name"],
                    tradeable_on_ge=raw["tradeable_on_ge"],
                    members=raw["members"],
                    noted=True,
                    noteable=True,
                    placeholder=False,
                    stackable=raw["stackable"],
                    equipable=raw["equipable"],
                    cost=raw["cost"],
                    lowalch=raw["lowalch"],
                    highalch=raw["highalch"],
                )

        except Exception as e:
            raise RuntimeError(f"Failed to load item data: {e}")

    def get_item_by_id(self, item_id: int) -> Optional[Item]:
        """
        Retrieves an item by its ID.
        """
        return self._items_by_id.get(item_id)

    def get_item_by_name(self, name: str) -> Optional[Item]:
        """
        Retrieves an item by its name (case-insensitive).
        """
        return self._items_by_name.get(name.lower())
    
    def get_item(self, item: Any) -> Optional[Item]:
        """
        Retrieves an item by its ID or name.
        
        If the input is an integer, it is treated as an item ID.
        If the input is a string, it is treated as an item name (case-insensitive).
        """
        if isinstance(item, int):
            return self.get_item_by_id(item)
        elif isinstance(item, str):
            return self.get_item_by_name(item)
        return None

    def search_items(self, query: str, limit: int = 50) -> Dict[int, Item]:
        """
        Searches for items whose names contain the query string (case-insensitive).
        
        Returns a dictionary of item IDs and their corresponding items, limited by the limit parameter.
        """
        if not query or not query.strip():
            return {}
            
        query = query.lower().strip()
        results = {}
        count = 0
        
        # First pass: exact matches get priority
        for item_id, item in self._items_by_id.items():
            if item.name.lower() == query:
                results[item_id] = item
                count += 1
                if count >= limit:
                    break
        
        # Second pass: starts with query
        if count < limit:
            for item_id, item in self._items_by_id.items():
                if item_id not in results and item.name.lower().startswith(query):
                    results[item_id] = item
                    count += 1
                    if count >= limit:
                        break
        
        # Third pass: contains query
        if count < limit:
            for item_id, item in self._items_by_id.items():
                if item_id not in results and query in item.name.lower():
                    results[item_id] = item
                    count += 1
                    if count >= limit:
                        break
        
        return results
    
    def search_items_advanced(self, query: str, filters: Dict[str, Any] = None, limit: int = 50) -> List[Item]:
        """
        Advanced search with filters and sorting.
        
        Args:
            query: Search term for item name
            filters: Dictionary of filters (tradeable_on_ge, members, stackable, etc.)
            limit: Maximum number of results to return
            
        Returns:
            List of Item objects sorted by relevance
        """
        if not query or not query.strip():
            return []
            
        # Get basic search results
        search_results = self.search_items(query, limit * 2)  # Get more for filtering
        results = list(search_results.values())
        
        # Apply filters if provided
        if filters:
            filtered_results = []
            for item in results:
                include = True
                for filter_key, filter_value in filters.items():
                    if hasattr(item, filter_key):
                        if getattr(item, filter_key) != filter_value:
                            include = False
                            break
                if include:
                    filtered_results.append(item)
            results = filtered_results
        
        # Sort by relevance (exact match first, then starts with, then contains)
        query_lower = query.lower()
        
        def relevance_score(item):
            name_lower = item.name.lower()
            if name_lower == query_lower:
                return 0  # Exact match - highest priority
            elif name_lower.startswith(query_lower):
                return 1  # Starts with - second priority
            else:
                return 2  # Contains - lowest priority
        
        results.sort(key=relevance_score)
        
        return results[:limit]

    def list_all_items(self) -> Dict[int, str]:
        """
        Returns a dictionary of all items with their IDs and names.
        """
        return {item.id: item.name for item in self._items_by_id.values()}


