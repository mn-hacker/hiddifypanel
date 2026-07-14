from flask import render_template, request, g
from flask_classful import FlaskView
from flask_babel import lazy_gettext as _
from datetime import date, timedelta
import calendar

from sqlalchemy import func

from hiddifypanel.auth import login_required
from hiddifypanel.database import db
from hiddifypanel.models import Role
from hiddifypanel.models.usage import DailyUsage
from hiddifypanel.models.user import User
from hiddifypanel.models.admin import AdminUser

ONE_GIG = 1024 ** 3


class UsageAdmin(FlaskView):

    @login_required(roles={Role.super_admin, Role.admin, Role.agent})
    def index(self):
        admin_id = request.args.get("admin_id", type=int) or g.account.id
        admin = AdminUser.query.filter(AdminUser.id == admin_id).first()
        sub_admins = admin.recursive_sub_admins_ids() if admin else [admin_id]

        today = date.today()
        # fetch 60 days so we can compare the current 30d window vs the previous one
        start60 = today - timedelta(days=59)
        rows = db.session.query(
            DailyUsage.date,
            func.coalesce(func.sum(DailyUsage.usage), 0),
            func.coalesce(func.sum(DailyUsage.online), 0),
        ).filter(
            DailyUsage.admin_id.in_(sub_admins),
            DailyUsage.date >= start60,
        ).group_by(DailyUsage.date).all()

        usage_map = {}
        for r in rows:
            key = r[0]
            if not isinstance(key, date):
                try:
                    key = date.fromisoformat(str(key)[:10])
                except Exception:
                    continue
            usage_map[key] = (int(r[1] or 0), int(r[2] or 0))

        # --- Current 30-day daily series (real data) ---
        start = today - timedelta(days=29)
        daily_series = []
        cur_bytes = 0
        cur_online_sum = 0
        for i in range(30):
            d = start + timedelta(days=i)
            used, online = usage_map.get(d, (0, 0))
            cur_bytes += used
            cur_online_sum += online
            daily_series.append({
                "date": d.strftime("%m/%d"),
                "usage_gb": round(used / ONE_GIG, 3),
                "online": online,
            })

        # --- Previous 30-day window (for month-over-month comparison) ---
        prev_start = today - timedelta(days=59)
        prev_bytes = 0
        prev_online_sum = 0
        for i in range(30):
            d = prev_start + timedelta(days=i)
            used, online = usage_map.get(d, (0, 0))
            prev_bytes += used
            prev_online_sum += online

        def pct(cur, prev):
            if prev and prev > 0:
                return round((cur - prev) / prev * 100, 1)
            return None

        # --- Forecast: project the current calendar month total ---
        month_start = today.replace(day=1)
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_elapsed = today.day
        month_bytes = 0
        for d, val in usage_map.items():
            if month_start <= d <= today:
                month_bytes += val[0]
        month_so_far_gb = round(month_bytes / ONE_GIG, 2)
        if days_elapsed > 0:
            projected_month_gb = round(month_bytes / days_elapsed * days_in_month / ONE_GIG, 2)
        else:
            projected_month_gb = month_so_far_gb

        # 7-day forward forecast line (flat average of the last 7 real days)
        last7 = [x["usage_gb"] for x in daily_series[-7:]]
        avg7 = round(sum(last7) / len(last7), 3) if last7 else 0
        forecast_series = []
        for i in range(1, 8):
            fd = today + timedelta(days=i)
            forecast_series.append({"date": fd.strftime("%m/%d"), "usage_gb": avg7})

        # --- Top users by usage (real data from User) ---
        top_q = User.query.filter(User.added_by.in_(sub_admins)).order_by(
            User.current_usage.desc()).limit(8).all()
        top_users = []
        for u in top_q:
            used = u.current_usage or 0
            if used <= 0:
                continue
            top_users.append({
                "name": (u.name or "unknown")[:22],
                "usage_gb": round(used / ONE_GIG, 2),
                "limit_gb": round((u.usage_limit or 0) / ONE_GIG, 2),
            })

        # --- Summary metrics ---
        s = DailyUsage.get_daily_usage_stats(admin_id)
        peak = max(daily_series, key=lambda x: x["usage_gb"]) if daily_series else None
        summary = {
            "total_30d_gb": round(cur_bytes / ONE_GIG, 2),
            "total_prev_gb": round(prev_bytes / ONE_GIG, 2),
            "total_change_pct": pct(cur_bytes, prev_bytes),
            "today_gb": round((s.get("today", {}).get("usage", 0) or 0) / ONE_GIG, 2),
            "avg_daily_gb": round(cur_bytes / ONE_GIG / 30, 2),
            "avg_change_pct": pct(cur_bytes, prev_bytes),
            "avg_online": round(cur_online_sum / 30, 1),
            "peak_gb": peak["usage_gb"] if peak else 0,
            "peak_date": peak["date"] if peak and peak["usage_gb"] > 0 else "-",
            "active_users": s.get("m5", {}).get("online", 0),
            "total_users": s.get("total", {}).get("users", 0),
            "month_so_far_gb": month_so_far_gb,
            "projected_month_gb": projected_month_gb,
            "month_progress_pct": round(days_elapsed / days_in_month * 100),
        }

        return render_template(
            "usage.html",
            daily_series=daily_series,
            forecast_series=forecast_series,
            top_users=top_users,
            summary=summary,
        )
