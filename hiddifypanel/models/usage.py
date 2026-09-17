import datetime
from datetime import timedelta, date

from flask import g
from sqlalchemy import func


from hiddifypanel.database import db



class DailyUsage(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date = db.Column(db.Date, default=datetime.date.today(), index=True)
    usage = db.Column(db.BigInteger, default=0, nullable=False)
    online = db.Column(db.Integer, default=0, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin_user.id'), default=0, nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey('child.id'), default=0, nullable=False)

    # def __str__(self):
    #     return str([id,date,usage,online,admin_id,child_id])

    @staticmethod
    def get_daily_usage_stats(admin_id=None, child_id=None):
        """The usage story of this admin: today, yesterday, the last 30 days, all of it.

        watashi v12.2.129.4: the four cards on the dashboard were counted four
        different ways and could not agree with each other or with the usage
        page:

          * "online" meant the number of distinct users last seen inside the
            window for today, the month and the total, but for yesterday it was
            the SUM of the online column of every DailyUsage row of that day -
            one row per admin per child - so a panel with children counted the
            same person several times over.
          * the month was DailyUsage.date >= today - 30, which is 31 days, while
            the usage page draws 30. Same label on screen, different number.
          * h24 and m5 reported a usage of 0, which reads as "no traffic". They
            were never measured at all.

        Now every window is defined once and every figure inside a window is
        taken the same way. Bytes always come from DailyUsage, the table the
        usage page and its charts also read, so the cards and the graphs cannot
        disagree any more. Heads are always distinct users by last_online.
        """
        from .admin import AdminUser
        from .user import User
        if not admin_id:
            admin_id = g.account.id
        admin = AdminUser.query.filter(AdminUser.id == admin_id).first()
        sub_admins = admin.recursive_sub_admins_ids() if admin else [admin_id]

        today = date.today()
        yesterday = today - timedelta(days=1)
        # 30 days means 30 days: today and the twenty nine before it, which is
        # exactly the window UsageAdmin draws.
        month_start = today - timedelta(days=29)
        now = datetime.datetime.now()
        midnight = datetime.datetime.combine

        def bytes_in(first=None, last=None):
            """Bytes recorded by day for this admin and its sub admins."""
            query = db.session.query(func.coalesce(func.sum(DailyUsage.usage), 0))
            query = query.filter(DailyUsage.admin_id.in_(sub_admins))
            if child_id:
                query = query.filter(DailyUsage.child_id == child_id)
            if first is not None:
                query = query.filter(DailyUsage.date >= first)
            if last is not None:
                query = query.filter(DailyUsage.date <= last)
            return int(query.scalar() or 0)

        def heads_since(moment):
            """Distinct users of this admin last seen at or after `moment`."""
            return User.query.filter(User.added_by.in_(sub_admins), User.last_online >= moment).count()

        # watashi v12.2.129.4: DailyUsage is written once a day per admin, so a
        # window shorter than a day has no bytes of its own to report. None
        # means "not measured here" and the page shows a dash for it.
        return {
            "today": {"usage": bytes_in(today, today),
                      "online": heads_since(midnight(today, datetime.time.min))},
            "h24": {"usage": None, "online": heads_since(now - timedelta(days=1))},
            "m5": {"usage": None, "online": heads_since(now - timedelta(minutes=5))},
            "yesterday": {"usage": bytes_in(yesterday, yesterday),
                          "online": heads_since(midnight(yesterday, datetime.time.min))},
            "last_30_days": {"usage": bytes_in(month_start, today),
                             "online": heads_since(midnight(month_start, datetime.time.min))},
            "total": {"usage": bytes_in(),
                      "online": heads_since(midnight(today - timedelta(days=3650), datetime.time.min)),
                      "users": User.query.filter(User.added_by.in_(sub_admins)).count()},
            "window": {"month_days": 30, "month_start": month_start.isoformat(),
                       "today": today.isoformat()},
        }
