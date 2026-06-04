from anews_agent.scheduler import create_push_scheduler


def test_create_push_scheduler_registers_two_hour_job():
    calls = []
    scheduler = create_push_scheduler(lambda: calls.append("run"))
    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == "anews-push"
    assert str(jobs[0].trigger).startswith("interval[2:00:00]")


def test_create_push_scheduler_prevents_overlapping_runs():
    scheduler = create_push_scheduler(lambda: None)
    job = scheduler.get_jobs()[0]

    assert job.coalesce is True
    assert job.max_instances == 1


def test_create_push_scheduler_uses_custom_interval_hours():
    scheduler = create_push_scheduler(lambda: None, interval_hours=1)
    jobs = scheduler.get_jobs()

    assert str(jobs[0].trigger).startswith("interval[1:00:00]")
