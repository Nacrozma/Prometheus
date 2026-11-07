# Pairing Atlas with Prometheus

This is optional. Atlas works fully on its own. Pairing lets Atlas consult Prometheus and share missions with
it on **this computer**. Each program keeps its own data, memory and keys.

## What you need

* Both programs on the same computer.
* Prometheus set up as usual, with its own `.env` provider keys, working on its own.
* *(Recommended)* the `keyring` package for Prometheus's Python: `pip install keyring`. Without it, the
  adapter refuses to store the pairing secret unless you pass `--allow-file-secret`.

## Steps

1. In the Prometheus folder, run:

   ```bash
   python sibling_adapter.py --pair
   ```

   It prints something like:

   ```
   [sibling] listening on 127.0.0.1:47653 (loopback only) · secrets: keyring
   [sibling] pairing code: ABCDE-FGH23  (valid 5 minutes, single use)
   ```

2. In Atlas, open **Siblings** (the cable icon on the left) → **Pair**. Enter the code and keep the address
   `127.0.0.1:47653`, then click **Pair**.
3. Atlas runs HELLO, CAPABILITIES and HEALTH_CHECK, then shows **connected**, with the tools Prometheus
   *reported* it has. Its dangerous tools are marked "refused".
4. Leave the adapter running while you want the link. Later, start it without `--pair`:
   `python sibling_adapter.py`.

## Using it

* **New mission** → choose a mode:
  * **Collaborative** (default): Atlas implements, in Atlas Forge with your approvals, and Prometheus reviews
    and proposes.
  * **Consultation:** ask for advice. One answer.
  * **Delegated:** Prometheus does the work with its own tools under its owner's rules.
* A mission is a draft until you click **Review & approve sending**, and then **Approve & send**. The
  approval shows exactly what leaves Atlas.
* Replies appear in the timeline, marked as coming from Prometheus. You decide what happens next: reply, ask
  for changes, accept, or cancel.
* In a normal conversation Atlas can also ask Prometheus a question with the `sibling.consult` tool. You
  approve each one, and you see the exact question and context first.

## Unpairing

* In Atlas: **Siblings → Unpair**. This deletes the secret from your credential store.
* On the Prometheus side: run `python sibling_adapter.py --list`, then
  `python sibling_adapter.py --revoke <sibling_id>`.

## Troubleshooting

| Message | Fix |
|---|---|
| "the sibling adapter is not running" | Start `python sibling_adapter.py` in the Prometheus folder. |
| "Pairing is not open" | Run it with `--pair` and use the new code within 5 minutes. |
| "The pairing code is wrong or has expired" | Five wrong tries invalidate the code; run `--pair` again. |
| "No secure credential store is available" (adapter) | `pip install keyring`, or run with `--allow-file-secret`. |
| "no longer accepts this pairing" | It was revoked on the Prometheus side. Pair again. |
| `--allow-dangerous` | Lets delegated missions *request* Prometheus's dangerous tools; you still confirm each one in its terminal. |
