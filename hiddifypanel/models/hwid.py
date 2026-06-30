import datetime

from hiddifypanel.database import db


class UserHWID(db.Model):
    """Hardware/device identifiers (HWID) reported by client apps for a user."""
    __tablename__ = 'user_hwid'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    hwid = db.Column(db.String(256), nullable=False)
    device_os = db.Column(db.String(64), default='', nullable=False)
    ver_os = db.Column(db.String(64), default='', nullable=False)
    device_model = db.Column(db.String(128), default='', nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.now)
    last_seen = db.Column(db.DateTime, nullable=False, default=datetime.datetime.now)

    __table_args__ = (db.UniqueConstraint('user_id', 'hwid', name='uq_user_hwid'),)


def get_user_hwids(user_id):
    return UserHWID.query.filter(UserHWID.user_id == user_id).order_by(UserHWID.last_seen.desc()).all()


def get_user_hwid_count(user_id):
    return UserHWID.query.filter(UserHWID.user_id == user_id).count()


def get_user_hwid_by_value(user_id, hwid):
    return UserHWID.query.filter(UserHWID.user_id == user_id, UserHWID.hwid == hwid).first()


def register_user_hwid(user_id, hwid, device_os='', ver_os='', device_model='', commit=True):
    now = datetime.datetime.now()
    rec = get_user_hwid_by_value(user_id, hwid)
    if rec:
        rec.last_seen = now
        if device_os:
            rec.device_os = device_os[:64]
        if ver_os:
            rec.ver_os = ver_os[:64]
        if device_model:
            rec.device_model = device_model[:128]
    else:
        rec = UserHWID(
            user_id=user_id,
            hwid=(hwid or '')[:256],
            device_os=(device_os or '')[:64],
            ver_os=(ver_os or '')[:64],
            device_model=(device_model or '')[:128],
            created_at=now,
            last_seen=now,
        )
        db.session.add(rec)
    if commit:
        db.session.commit()
    return rec


def delete_user_hwid(user_id, hwid, commit=True):
    rec = get_user_hwid_by_value(user_id, hwid)
    if rec:
        db.session.delete(rec)
        if commit:
            db.session.commit()
        return True
    return False


def reset_user_hwids(user_id, commit=True):
    n = UserHWID.query.filter(UserHWID.user_id == user_id).delete()
    if commit:
        db.session.commit()
    return n
