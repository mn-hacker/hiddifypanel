# watashi v12.3.41dev: the inbounds the owner builds by hand in the advanced mode.
"""One row is one inbound, described the way x-ui, Marzban and Pasargad
describe theirs: a protocol, a port, a transport and a security layer. The
fields that only some combinations need (a path, a service name, the REALITY
keys and so on) live in the settings column as JSON, so a new knob never needs
a new column and an older panel can still read the table.

Every user of the panel is a client of every enabled row, exactly like the
inbounds the panel builds by itself; the clients are written by the template
xray/configs/05_inbounds_90_custom.json.j2 and kept in step through the xray
API, so the usage of these inbounds is counted on the same user counters.

watashi v12.3.42dev: a row of a sing-box protocol (SINGBOX_PROTOCOLS) is a
sing-box inbound instead, written by singbox/configs/05_inbounds_90_custom.json.j2;
sing-box has no user API, so its users follow every user change through the
apply-users path, which restarts sing-box anyway.
"""
import datetime
import json

from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime

from watashipanel.database import db

# watashi v12.3.42dev: these protocols are served by sing-box, every other one
# by xray. The core follows from the protocol, so the table needs no new column
# and a backup of this release still restores on the one before it.
SINGBOX_PROTOCOLS = ('hysteria2', 'tuic', 'anytls', 'naive', 'shadowtls', 'ss2022', 'snell')


class CustomInbound(db.Model):  # type: ignore
    __tablename__ = 'custom_inbound'
    id = Column(Integer, primary_key=True, autoincrement=True)
    child_id = Column(Integer, default=0, nullable=False)
    enable = Column(Boolean, default=True, nullable=False)
    remark = Column(String(128), default='', nullable=False)
    protocol = Column(String(16), default='vless', nullable=False)
    port = Column(Integer, nullable=False)
    listen = Column(String(64), default='', nullable=False)
    network = Column(String(16), default='tcp', nullable=False)
    security = Column(String(16), default='none', nullable=False)
    settings = Column(Text, default='{}')
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def tag(self) -> str:
        # The xray driver recognises its own inbounds by this prefix, so it must
        # never contain one of the words it maps to a protocol (vless, ss, ...).
        return f'custom-{self.id}'

    @property
    def core(self) -> str:
        # watashi v12.3.42dev: which core serves this row, xray or singbox
        return 'singbox' if self.protocol in SINGBOX_PROTOCOLS else 'xray'

    @property
    def opts(self) -> dict:
        try:
            value = json.loads(self.settings or '{}')
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    @opts.setter
    def opts(self, value: dict):
        self.settings = json.dumps(value or {}, ensure_ascii=False, sort_keys=True)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'enable': bool(self.enable),
            'remark': self.remark or '',
            'protocol': self.protocol,
            'port': int(self.port or 0),
            'listen': self.listen or '',
            'network': self.network,
            'security': self.security,
            'settings': self.opts,
            'core': self.core,  # watashi v12.3.42dev: read only, from_dict ignores it
        }

    @staticmethod
    def from_dict(row: dict, keep_id: bool = True) -> 'CustomInbound':
        one = CustomInbound()
        if keep_id and row.get('id'):
            one.id = int(row['id'])
        one.child_id = 0
        one.enable = bool(row.get('enable', True))
        one.remark = str(row.get('remark') or '')[:128]
        one.protocol = str(row.get('protocol') or 'vless')[:16]
        one.port = int(row.get('port') or 0)
        one.listen = str(row.get('listen') or '')[:64]
        one.network = str(row.get('network') or 'tcp')[:16]
        one.security = str(row.get('security') or 'none')[:16]
        settings = row.get('settings')
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except Exception:
                settings = {}
        one.opts = settings if isinstance(settings, dict) else {}
        return one

    @staticmethod
    def all_rows() -> list['CustomInbound']:
        try:
            return CustomInbound.query.filter(CustomInbound.child_id == 0).order_by(CustomInbound.id).all()
        except Exception:
            # the table is created by the migration of this release; until it
            # ran there simply are no hand built inbounds.
            db.session.rollback()
            return []

    @staticmethod
    def bulk_register(rows: list, commit: bool = True):
        """Backup restore: the section replaces what is there, row for row."""
        if not isinstance(rows, list):
            return
        CustomInbound.query.delete()
        for row in rows:
            if not isinstance(row, dict) or not row.get('port'):
                continue
            try:
                db.session.add(CustomInbound.from_dict(row))
            except (TypeError, ValueError) as problem:
                # one broken row of a hand edited file is skipped, not the restore
                print('a custom inbound of the backup was skipped', problem)
        if commit:
            db.session.commit()
