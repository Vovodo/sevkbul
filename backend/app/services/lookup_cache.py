from sqlalchemy.orm import Session, joinedload

from app.models import Shipment, ShipmentLabel, ShipmentStatus, ShipmentLabelStatus, InventoryLabel


class LookupCache:
    """In-memory O(1) lookup for active shipment FIFO pools."""

    def __init__(self):
        self._pools: dict[int, dict[str, str]] = {}
        self._label_data: dict[int, dict[str, dict]] = {}
        self._ref_context: dict[int, dict[str, str]] = {}
        self._all_labels: dict[str, InventoryLabel] = {}
        self._global_label_shipment: dict[str, int] = {}

    def load_shipment(self, db: Session, shipment_id: int):
        shipment = (
            db.query(Shipment)
            .options(
                joinedload(Shipment.shipment_labels)
                .joinedload(ShipmentLabel.inventory_label)
            )
            .filter(Shipment.id == shipment_id)
            .first()
        )
        if not shipment:
            return

        pool: dict[str, str] = {}
        label_data: dict[str, dict] = {}
        ref_context: dict[str, str] = {}
        pool_label_set: set[str] = set()

        for sl in shipment.shipment_labels:
            inv = sl.inventory_label
            if not inv:
                continue

            pool_label_set.add(inv.label)
            self._all_labels[inv.label] = inv

            if sl.status == ShipmentLabelStatus.SCANNED:
                pool[inv.label] = "already_scanned"
            else:
                pool[inv.label] = "in_pool"
                self._global_label_shipment[inv.label] = shipment_id

            label_data[inv.label] = {
                "shipment_label_id": sl.id,
                "label": inv.label,
                "reference": inv.reference,
                "allocated_quantity": float(sl.allocated_quantity),
                "total_quantity": float(inv.quantity),
                "fifo_date": inv.fifo_date.isoformat(),
                "fifo_group_date": inv.fifo_date.date().isoformat(),
                "status": sl.status.value,
            }

        ref_inventory = (
            db.query(InventoryLabel)
            .filter(InventoryLabel.reference == shipment.reference)
            .all()
        )
        for inv in ref_inventory:
            self._all_labels[inv.label] = inv
            if inv.label not in pool_label_set:
                ref_context[inv.label] = "fifo_outside"

        self._pools[shipment_id] = pool
        self._label_data[shipment_id] = label_data
        self._ref_context[shipment_id] = ref_context

    def unload_shipment(self, shipment_id: int):
        pool = self._pools.pop(shipment_id, None)
        if pool:
            for label in pool:
                self._global_label_shipment.pop(label, None)
        self._label_data.pop(shipment_id, None)
        self._ref_context.pop(shipment_id, None)

    def rebuild_global_index(self):
        self._global_label_shipment.clear()
        for sid, pool in self._pools.items():
            for label, status in pool.items():
                if status == "in_pool":
                    self._global_label_shipment[label] = sid

    def global_lookup(self, label: str) -> tuple[str | None, int | None]:
        """O(1) global etiket araması."""
        for sid, pool in self._pools.items():
            if label in pool:
                return pool[label], sid

        for sid, ref_ctx in self._ref_context.items():
            if label in ref_ctx:
                return ref_ctx[label], sid

        if label in self._all_labels:
            return "wrong_reference", None

        return None, None

    def lookup(self, shipment_id: int, label: str) -> str | None:
        pool = self._pools.get(shipment_id, {})
        if label in pool:
            return pool[label]
        ref_context = self._ref_context.get(shipment_id, {})
        if label in ref_context:
            return ref_context[label]
        if label in self._all_labels:
            return "wrong_reference"
        return None

    def mark_scanned(self, shipment_id: int, label: str):
        pool = self._pools.get(shipment_id)
        if pool is not None:
            pool[label] = "already_scanned"
        self._global_label_shipment.pop(label, None)
        data = self._label_data.get(shipment_id, {}).get(label)
        if data:
            data["status"] = "scanned"

    def unmark_scanned(self, shipment_id: int, label: str):
        pool = self._pools.get(shipment_id)
        if pool is not None:
            pool[label] = "in_pool"
        self._global_label_shipment[label] = shipment_id
        data = self._label_data.get(shipment_id, {}).get(label)
        if data:
            data["status"] = "pending"

    def get_label_data(self, shipment_id: int, label: str) -> dict | None:
        return self._label_data.get(shipment_id, {}).get(label)

    def get_pool(self, shipment_id: int) -> dict[str, dict]:
        return self._label_data.get(shipment_id, {})

    def has_active_shipments(self) -> bool:
        """Aktif veya tamamlanmış sevkiyat havuzu yüklü mü."""
        return len(self._pools) > 0

    def load_all_active(self, db: Session):
        all_labels = db.query(InventoryLabel).all()
        self._all_labels = {l.label: l for l in all_labels}
        self._pools.clear()
        self._label_data.clear()
        self._ref_context.clear()
        self._global_label_shipment.clear()

        active = db.query(Shipment).filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED])).all()
        for s in active:
            self.load_shipment(db, s.id)

    def reload_inventory_labels(self, db: Session):
        all_labels = db.query(InventoryLabel).all()
        self._all_labels = {l.label: l for l in all_labels}
        for shipment_id in list(self._pools.keys()):
            self.load_shipment(db, shipment_id)


lookup_cache = LookupCache()
