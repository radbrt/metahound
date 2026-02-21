"""
APScheduler setup. Fires one-shot alert jobs after each ingest.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.models import Anomaly, Org

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started")


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


def schedule_alert_job(org: Org, anomalies: list[Anomaly], db_session_factory) -> None:
    """
    Schedule a one-shot job that sends alerts for the given anomalies.
    Uses a fresh DB session inside the job to avoid cross-thread issues.
    """
    from app.services.alert_service import send_alerts

    anomaly_ids = [a.id for a in anomalies]
    org_id = org.id

    def _job():
        from app.database import SessionLocal
        from app.models import Anomaly as AnomalyModel, Org as OrgModel

        db = SessionLocal()
        try:
            org_obj = db.query(OrgModel).filter(OrgModel.id == org_id).first()
            anomaly_objs = db.query(AnomalyModel).filter(AnomalyModel.id.in_(anomaly_ids)).all()
            if org_obj and anomaly_objs:
                send_alerts(org_obj, anomaly_objs)
                for a in anomaly_objs:
                    a.alert_sent = True
                db.commit()
        except Exception as exc:
            logger.error("Alert job failed: %s", exc)
        finally:
            db.close()

    get_scheduler().add_job(_job, "date")  # fires immediately
