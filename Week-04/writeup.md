## What I Built

I built an HR agent that answers employee emails using company policies and employee records. For each email, Claude decides which tools to call from an MCP server: `search_policy` searches the HR policy documents, and `get_leave_balance` looks up the sender's leave balance in the employee file. The agent then saves a draft reply with `save_reply` and marks whether it needs human review. Nothing is sent.

To make it work for Ridgeline Hotels, I added the `--org` option to `agent.py` and `hr_mcp_server.py`. It names an organization folder (`ridgeline-hotels`) and loads that organization's policy documents, employee file and system prompt. Without `--org`, the agent still uses `hartwell-hr`. Each organization has its own Chroma search database, kept out of Git. Ridgeline's employee file uses different column names from Hartwell's (`Email Address`, `PTO Days Remaining`, `Sick Days Remaining`), so the server works out which columns hold the email address and the balances from the header row instead of assuming fixed names. I also made `--save` work with `--email`, so each run is written to a UTF-8 text file.

I ran all seven Ridgeline sample emails and saved the results as `runs/ridgeline-01.txt` through `runs/ridgeline-07.txt`.

## Why This Approach

Task A: Script. Adding earned PTO every night is a repetitive process with fixed rules and does not require model reasoning. A scheduled script can reliably perform the calculation.

Task B: One model call. Rewriting the PTO policy into a one-page FAQ is a straightforward content-generation task that can be completed with a single prompt and response.

Task C: Agent. A supervisor scheduling request may require checking staffing records, shift availability, scheduling policies or multiple data sources. An agent is appropriate because it can decide what information to retrieve before responding.

Email 5 protection: Code. The agent must not reveal other employees' information. The MCP server is started for each email with the sender's address, so `get_leave_balance` can only return the sender's own record, and no prompt wording can make it look up anyone else.

## Example Run

```text
Sender: danielle.price@ridgelinehotels.example
Subject: A guest
Email: Week-04/ridgeline-hotels/sample-emails/06-danielle-guest.eml
Organization: ridgeline-hotels
Model: claude-sonnet-5

Tools offered: search_policy, get_leave_balance, save_reply

Step 1: save_reply
  inputs: {"reply_text": "Hi Danielle,\n\nThank you for trusting us with this, and I'm very sorry you're going through this. What you're describing is serious, and you shouldn't have to just \"avoid the room\" or deal with this kind of treatment at work.\n\nI'm flagging this right away so that someone from our People and Culture team can personally follow up with you as soon as possible to discuss what's happened and the best next steps. You'll hear from a person directly rather than me, given the nature of this situation.\n\nIn the meantime, please take care of yourself, and don't hesitate to reach out if anything else happens.\n\nWarm regards,\nHR Assistant (on behalf of the People and Culture team)", "needs_human_review": true}
  result: Draft saved to Week-04\drafts\06-danielle-guest-20261117-131823.txt. Nothing was sent.

[Claude] I've drafted a reply to Danielle and flagged it for immediate human review, since this involves guest harassment and a safety concern that her supervisor dismissed. The draft acknowledges her situation with care, avoids giving policy advice on handling it myself, and makes clear that a People and Cu...

----------------------------------------------------------------------
Stopped: Claude replied without a tool request (stop_reason: end_turn).
Tool calls: 1

Saved to: Week-04\drafts\06-danielle-guest-20261117-131823.txt (not sent)
To: Danielle Price <danielle.price@ridgelinehotels.example>
Subject: [NEEDS HR REVIEW] Re: A guest

DRAFT
Hi Danielle,

Thank you for trusting us with this, and I'm very sorry you're going through this. What you're describing is serious, and you shouldn't have to just "avoid the room" or deal with this kind of treatment at work.

I'm flagging this right away so that someone from our People and Culture team can personally follow up with you as soon as possible to discuss what's happened and the best next steps. You'll hear from a person directly rather than me, given the nature of this situation.

In the meantime, please take care of yourself, and don't hesitate to reach out if anything else happens.

Warm regards,
HR Assistant (on behalf of the People and Culture team)
Needs human review: true
Tokens for this email: 3351 input, 556 output
```

## Reflection

Email 3 tools: `get_leave_balance`, `search_policy`, `search_policy`, `save_reply`. This order made sense because the agent first checked Brittany's balance (4 PTO days) to see whether she had enough for 6 days off. It then searched the PTO policy twice, first for the rules on requesting consecutive days and then for borrowing options once it knew she was short, and saved the reply only after it had both the balance and the policy.

Email 6 flagged: Yes. The draft told Danielle that her situation is serious, that she shouldn't have to just avoid the room, that it was being flagged right away, and that someone from the People and Culture team would personally follow up with her.

Email 7 balance lookup: Error. The balance tool found no employee record for logan.brooks@ridgelinehotels.example. The draft welcomed Logan, told him his leave record couldn't be found, gave no PTO number, and said a member of the People and Culture team would follow up with his accurate balance.
