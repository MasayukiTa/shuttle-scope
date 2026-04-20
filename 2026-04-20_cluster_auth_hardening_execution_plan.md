# 2026-04-20 Cluster / Auth Hardening Execution Plan

## Goal

Today's goal is not to redesign ShuttleScope into a perfectly clean architecture.
Today's goal is to keep the current heterogeneous Ray workflow alive while removing the most dangerous exposure paths.

The key rule for today:

- do not break the current Ray-based heterogeneous execution path
- do not disable the worker firewall globally anymore
- do not try to replace Ray with Docker today
- harden the control plane first, not the data plane

In other words:

- keep the compute path working
- reduce the blast radius
- separate cluster control from normal app access

## Scope For Today

This plan is intentionally narrow.
Do not try to finish every auth problem in one night.
If you do that, you will break the cluster again.

Today's target is only these three things:

1. restore firewall safety on K10 while preserving Ray connectivity
2. lock down dangerous cluster / local-file control endpoints
3. keep old fallback auth paths only where explicitly allowed

## Non-Goals For Today

Do not do these today:

- full auth redesign
- full RBAC redesign across all routes
- Docker migration
- replacing Ray with another distributed runtime
- rewriting all cluster bootstrap code
- removing all X-Role compatibility everywhere at once
- large frontend UX redesign

## Success Criteria

At the end of today, all of the following should be true:

- K10 firewall is enabled again
- Ray cluster still connects between X1 AI and K10
- cluster control endpoints are no longer broadly exposed
- video local-path execution is no longer broadly exposed
- old header-based auth remains only in explicitly limited situations
- current benchmark / worker routing path still works

---

## Phase 0: Freeze a Known-Good Smoke Path

Before changing anything, define the exact minimum workflow that must keep working.
If you do not freeze this first, you will not know what you broke.

### Smoke workflow to preserve

1. start X1 AI primary
2. start or join K10 worker
3. confirm `/cluster/status` reports running / connected state
4. confirm worker visibility in Settings or cluster API
5. run one light benchmark or one light remote task
6. verify result returns successfully

### Record now

Write these down before editing code:

- current K10 IP on the dedicated cluster path
- current X1 AI IP on the dedicated cluster path
- which interface is used for Ray today
- which command currently makes K10 join successfully
- which cluster API calls are required to get from cold start to usable state

If needed, save this as a temporary local text note before code edits.

---

## K10: Tasks To Do Today

## 1. Re-enable Windows Firewall

Current state is unacceptable.
Do this first.

- turn Windows Firewall back on
- confirm the active network profile for the cluster interface
- if possible, mark the cluster link as a Private profile, not Public
- do not leave the whole machine open just because Ray was painful

## 2. Restrict inbound access to the dedicated cluster path only

Create allow rules only for the X1 AI source IP or the dedicated cluster subnet.
Do not allow general Wi-Fi / LAN access.

Minimum intent:

- allow inbound only from X1 AI cluster IP
- allow only the ports actually needed for the current Ray path
- block the same ports from other interfaces / profiles if possible

Important:

- do not optimize for convenience
- optimize for “X1 can talk to K10, others cannot”

## 3. Validate the worker environment after firewall restoration

After firewall rules are tightened:

- retry the current join command
- confirm the worker still appears from X1 AI
- confirm one benchmark or small remote task still runs

If it fails, do not disable the firewall again.
Instead, identify the missing rule and add only that rule.

## 4. Keep K10 as a worker, not an operator surface

Operational rule for now:

- K10 should not expose broad app access
- K10 is a compute worker first
- do not use K10 as a casually open management target

---

## X1 AI: Tasks To Do Today

## 1. Confirm the cluster interface and trust boundary

On X1 AI, explicitly decide which interface is the cluster path.
Do not leave this ambiguous.

Record:

- cluster NIC name
- cluster IP
- whether Wi-Fi is also active
- whether Ray is accidentally reachable beyond the dedicated path

## 2. Treat X1 AI as the only cluster control origin

For today's hardening, assume:

- X1 AI is the only machine allowed to perform cluster control
- K10 should only accept Ray / worker-related traffic from X1 AI

This means you should structure firewall and endpoint policy around that assumption.

## 3. Test the exact control actions you actually use

From X1 AI, list the exact actions you need today:

- read cluster status
- read worker nodes
- start head if needed
- join worker if needed
- detect worker hardware if needed
- run benchmark / remote task

Anything you do not actually need today should not remain broadly accessible.

## 4. Keep tunnel / public-exposure paths away from cluster control

If any tunnel or browser-exposed path exists on X1 AI:

- do not allow that path to reach dangerous cluster control endpoints
- do not let operator convenience leak into public or semi-public access paths

---

## Source Code: Tasks To Do Today

This is the most important section.
Do not refactor everything.
Add a narrow policy layer and use it to gate dangerous control paths.

## A. Add a small control-plane policy module

Create one backend module dedicated to access policy for dangerous operations.
For example:

- `backend/utils/control_plane.py`

The module should centralize decisions like:

- is this request from loopback?
- is this request from the dedicated trusted cluster subnet?
- is legacy header auth allowed here?
- is select login allowed here?
- is bootstrap admin seeding allowed here?
- is operator-token protected control allowed here?

Suggested functions:

- `is_loopback_request(request) -> bool`
- `is_trusted_cluster_request(request) -> bool`
- `require_local_or_operator_token(request) -> None`
- `allow_legacy_header_auth(request) -> bool`
- `allow_select_login(request) -> bool`
- `allow_seed_admin(request) -> bool`
- `allow_local_file_control(request) -> bool`

Keep it small.
The point is not perfection.
The point is to stop spreading policy decisions across random files.

## B. Restrict legacy header auth instead of deleting it today

Target files:

- `shuttlescope/backend/utils/auth.py`
- `shuttlescope/src/api/client.ts`

### Backend change

In `backend/utils/auth.py`:

Current behavior:

- valid JWT => use JWT
- otherwise fallback to `X-Role` / `X-Player-Id` / `X-Team-Name`

Today's change:

- keep JWT as primary
- allow header fallback only if explicitly permitted by policy
- for now, permit it only for loopback or explicitly trusted dev mode

Do not remove the code path entirely today.
That is how you accidentally break old local flows.
Just make it conditional.

### Frontend change

In `src/api/client.ts`:

Current behavior:

- no token => automatically send `X-Role` / `X-Player-Id` / `X-Team-Name`

Today's change:

- keep the fallback only for local compatibility mode
- do not silently send role headers in every no-token situation
- ideally gate it behind a narrow compatibility flag or local-only condition

If this is too risky for today, backend-side restriction is the mandatory part.
Frontend-side restriction is desirable but secondary.

## C. Restrict select login

Target file:

- `shuttlescope/backend/routers/auth.py`

Current behavior:

- `grant_type == "select"` issues JWT for coach / analyst without password

Today's change:

- do not remove the feature completely today
- restrict it to loopback or explicitly trusted operator context
- reject it for normal LAN / tunnel / browser-exposed requests

Reason:

This path is convenience for local internal use, not a generally exposed auth mode.

## D. Restrict default admin seeding

Target file:

- `shuttlescope/backend/routers/auth.py`

Current behavior:

- if no admin exists, create default admin with fixed password

Today's change:

- do not keep this broadly reachable
- allow it only when policy says local bootstrap is allowed
- at minimum require loopback request
- better: require an explicit bootstrap environment flag as well

Suggested minimal rule for today:

- no admin exists
- request is loopback
- bootstrap mode env flag is enabled

If those conditions are not met, do not auto-seed.

## E. Lock down dangerous cluster control endpoints

Target file:

- `shuttlescope/backend/routers/cluster.py`

Do not overcomplicate read vs write right now.
Just protect the dangerous paths first.

### High-risk endpoints to gate today

Protect these with `require_local_or_operator_token()` or equivalent:

- `POST /cluster/config`
- `POST /cluster/ray/start`
- `POST /cluster/ray/start-head`
- `POST /cluster/ray/stop`
- `POST /cluster/nodes/{worker_ip}/detect`
- `POST /cluster/nodes/{worker_ip}/ray-join`
- `GET /cluster/network/arp`

Read-only endpoints can be reviewed afterward, but the above should not remain casually callable.

## F. Lock down local-file execution path

Target file:

- `shuttlescope/backend/routers/video_import.py`

Current problem:

- `/video_import/path` accepts a local path and launches analysis

Today's change:

- keep the feature
- treat it as a control-plane operation
- require local or operator token policy for it

Do not leave local-path execution broadly available.

## G. Keep main logic changes minimal

Do not rewrite `backend/main.py` today.
You are not in cleanup mode.
You are in risk-reduction mode.

The only acceptable `main.py` changes today are:

- import and wire a small new policy helper if absolutely necessary
- optionally add env-driven settings used by the policy layer

Anything larger is scope creep.

---

## Suggested Operator Token Design For Today

Do not build a complex secret-management solution tonight.
That is not the bottleneck.

Use a simple environment-configured operator token for dangerous control endpoints.

Possible environment variable:

- `SS_OPERATOR_TOKEN`

Behavior:

- if request is loopback, allow
- else require `X-Operator-Token` header to match `SS_OPERATOR_TOKEN`
- if token is absent or wrong, reject

This is not perfect security.
It is still far better than broad unauthenticated control access.
And it is small enough to implement tonight without wrecking the cluster.

---

## Recommended Order Of Work Tonight

## Step 1: Freeze current cluster smoke flow

Do not skip.
Write it down.

## Step 2: Fix K10 firewall first

- re-enable firewall
- add narrow allow rules
- verify Ray join still works

Do this before major code edits.
Otherwise you will not know whether a failure is network or code.

## Step 3: Add backend control-plane policy module

Keep it tiny.
No grand design.
Just enough to gate dangerous paths.

## Step 4: Gate cluster dangerous endpoints

This gives the highest risk reduction with the least chance of breaking compute dispatch.

## Step 5: Gate `/video_import/path`

Quick win. Dangerous endpoint. Easy to classify.

## Step 6: Gate `select` login and admin seed

These are important, but do them after cluster control is protected.

## Step 7: Restrict backend legacy header auth

Do this after the control endpoints are gated.
Do not start here.
If you start here, you may break more than you can diagnose quickly.

## Step 8: Optional frontend cleanup

Only after backend protections are in place.
Frontend cleanup should not be the first defense layer.

---

## Concrete File Touch List

### K10 / network / ops

- Windows Firewall rules on K10
- current worker join command / startup path
- verify dedicated cluster interface/IP assumptions

### X1 AI / ops

- confirm cluster NIC / source IP
- confirm only X1 AI should perform control-plane actions
- test current smoke workflow before and after changes

### Source code

- `shuttlescope/backend/utils/control_plane.py` (new)
- `shuttlescope/backend/utils/auth.py`
- `shuttlescope/backend/routers/auth.py`
- `shuttlescope/backend/routers/cluster.py`
- `shuttlescope/backend/routers/video_import.py`
- `shuttlescope/src/api/client.ts` (optional but recommended)

---

## What To Check Before Ending Tonight

Before finishing, verify all of the following:

- K10 firewall is on
- X1 AI can still connect to K10 for Ray / worker operation
- worker detection or benchmark still works
- dangerous cluster write endpoints now reject requests without local/operator authority
- `/video_import/path` rejects unauthorized requests
- `grant_type=select` no longer works from a broad remote context
- default admin seed no longer happens from a non-local broad context

If any of the above fails, do not keep layering changes.
Stop, restore the smoke path, and isolate the smallest broken step.

---

## Brutal Priority Reminder

If time runs out, prioritize in this exact order:

1. K10 firewall back on
2. cluster dangerous endpoints gated
3. `/video_import/path` gated
4. `select` login gated
5. admin seed gated
6. legacy header auth restricted
7. frontend cleanup

Do not waste tonight chasing architectural beauty.
Your actual problem is not ugliness.
Your actual problem is that dangerous control paths are too exposed while cluster connectivity is fragile.

That is what tonight must fix.
