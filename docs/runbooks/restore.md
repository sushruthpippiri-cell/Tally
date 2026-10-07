# Backup and recovery (P16.6)

Provider-neutral by decision (D-056 #2): hosting is managed PostgreSQL with point-in-time
recovery in an Indian region, but the vendor is not chosen, so this says **what must be true**
and how to check it — not which buttons to press in one console.

**Nothing here has been run.** There is no hosting and no staging environment yet, so BKP-1.2 is
recorded as blocked in `docs/progress.md`. The scripts exist and their logic is tested; the drill
itself waits on the owner.

## The targets (BKP-1.4, D-056 #1)

| | Target | Means |
|---|---|---|
| **RPO** — how much data may be lost | **≤ 24 hours** | A restore may lose at most a day of syncs. Continuous WAL archiving normally makes the real figure minutes, not hours. |
| **RTO** — how long recovery may take | **≤ 4 hours** | From the decision to restore to the service answering again. |

These are the **committed worst case**, not a prediction. The drill records what was *achieved*,
because a drill that restates the target proves nothing.

What the targets mean in practice: at most a day of synced records are lost, and **a fresh full
sync brings back everything that still exists in Tally** (BKP-1.5). The only data a backup is
the sole source for is records **deleted from Tally** — those exist nowhere else, which is why
this project never hard-deletes (CLAUDE.md rule 5) and why the backup matters at all.

## What the provider must be configured to do (BKP-1.1)

Check each of these in the provider's console and record the answer in `docs/progress.md`:

1. **A daily full backup.** Note the time it runs; it should not overlap the start-of-day
   scheduled syncs.
2. **Continuous WAL archiving**, giving point-in-time recovery between the full backups. This is
   what makes the real RPO minutes rather than a day.
3. **At least 30 days of retention.** 30 is the floor in BKP-1.1; a discrepancy in the books is
   often noticed weeks later, so prefer 35 if the cost is small.
4. **Backups in the same Indian region**, and encrypted at rest.
5. **The database reachable only from the backend**, not from the public internet.

## A failed backup must raise an alert (BKP-1.3)

> "A failed backup raises an alert; it is never skipped silently."

This is the requirement most easily left half-done, because a provider that emails on failure
looks like it satisfies it until the email goes to a mailbox nobody reads.

- Point the provider's backup-failure notification at a destination a person actually sees — the
  on-call channel, not a shared inbox.
- Add a check that **alerts on the absence of a recent successful backup**, not only on a
  reported failure. A backup job that never ran reports nothing at all, and that is the failure
  mode this requirement exists for.
- **Test the alert** by making a backup fail on purpose once (revoke the backup role's
  permission, or point it at a full volume), and confirm a human was told. Record the date.

## Taking the snapshot the drill compares against (BKP-1.2)

```sh
cd deploy/backup
DATABASE_URL="$PRODUCTION_READONLY_URL" ./take_snapshot.sh > snapshots/$(date -u +%F).json
```

The snapshot holds the row counts of every table that carries data, **and** each company's
latest reconciliation run with its figures. Row counts alone would pass a restore that brought
back the right *number* of wrong rows; the reconciliation figures are the numbers a business
would notice. Commit the snapshot, or keep it with the backup — the drill is worthless without
the "known" half of "compare with a known snapshot".

## The drill

```sh
cd deploy/backup
export STAGING_DATABASE_URL="postgresql://…/tally_staging"
export RESTORE_COMMAND='…'          # your provider's restore, into the staging database
./restore_drill.sh --snapshot snapshots/2026-10-07.json
```

The script refuses any database whose name does not end in `_staging`, so it cannot restore over
production — the one mistake here that could not be undone. It does not guess
`RESTORE_COMMAND`: a managed instance restores through its own API into a new instance, a
self-hosted one with `pg_restore` or pgBackRest. Whatever you use, **write it into this file**
so the next person does not have to work it out while the service is down.

It then runs `compare_snapshot.py`, which exits non-zero on any difference in a row count or a
reconciliation figure, naming each.

Afterwards, record in `docs/progress.md`: the date, the **achieved** RTO (the script prints its
own elapsed time), the backup's age at restore (the achieved RPO), the provider and region, and
the snapshot id.

## Recovering for real

1. **Stop writes.** Scale the backend to zero, or stop the container. Agents will queue their
   uploads and retry with backoff; nothing is lost (BKP-1.6) and nothing half-written reaches
   the restored database.
2. **Choose the recovery point.** For a lost instance, the latest. For bad data — a faulty sync,
   a mistaken bulk change — the moment *before* it, which is what point-in-time recovery is for.
3. **Restore**, into a new instance if the provider works that way.
4. **Check before letting anyone in**: run `compare_snapshot.py --url <restored>` against the
   most recent snapshot, and open the Reconciliation page for one company.
5. **Point the backend at the restored instance** and start it.
6. **Run a full sync per company.** This is the step that matters: a full sync restores every
   record that still exists in Tally (BKP-1.5), so the gap between the recovery point and now
   closes itself. Only records deleted from Tally in that window stay as the backup left them.
7. **Run reconciliation** and confirm it passes before telling anyone the service is back.

## The Agent queues are not backed up (BKP-1.6)

Deliberately. An Agent's local queue is a transient copy of what it has just read from Tally: if
it is lost, the next full or incremental sync re-pulls the same records from Tally itself. Backing
it up would mean backing up a cache, on machines we do not administer, holding business data
outside the database — a bigger exposure than the thing it protects.

The Agent's **credential** is not in the queue; it is in the Windows secret store, and if lost it
is re-issued by rotating it from the dashboard (UC-9), not restored.
