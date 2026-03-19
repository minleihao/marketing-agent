# Marketing Copilot User Guide

This guide is for marketers, content teams, and campaign managers who want to use Marketing Copilot without needing a technical background.

## What This Tool Does

Marketing Copilot helps you:

- brainstorm campaign ideas
- write or rewrite marketing copy
- save chat history by project
- reuse approved brand guidance
- share work with a team or company group

Think of it as a shared marketing workspace with chat, brand guidance, and team collaboration in one place.

## A Few Simple Terms

- Conversation: one saved chat thread
- Marketing task: a conversation with extra marketing fields like channel, audience, and objective
- Knowledge Base: a reusable brand reference the assistant can follow
- Group: a team access list

## Quick Start

### 1. Sign in or create your account

On the first screen, you can:

- log in with your username and password
- register a new account
- optionally request access to one or more groups during registration

Basic rules:

- username must be 3 to 32 characters
- password must be at least 8 characters

If you are prompted to change your password, do that first.

### 2. Open the main workspace

After logging in, you will land on the main app page.

The page has 3 main parts:

- left sidebar: your saved conversations
- top controls: model, thinking depth, task mode, sharing, export, and rename/delete options
- main area: messages, marketing brief fields, and file upload

### 3. Start the right kind of conversation

Use:

- `+ Chat` for general questions, rewriting, summaries, and brainstorming
- `+ Marketing` for structured work such as campaign copy, landing page messaging, email drafts, or channel-specific assets

If you are not sure, start with `+ Marketing`.

## Everyday Use

### Create a marketing task

Click `+ Marketing`.

You will see a short brief form with these fields:

- Channel: where the content will be used, such as email, LinkedIn, X, WeChat, landing page, or other
- Product: what you are promoting
- Audience: who the message is for
- Objective: what you want the content to achieve
- Extra Requirements: any must-have points, tone notes, limits, or calls to action
- Output Sections: the parts you want returned

For most day-to-day work:

- keep `Marketing Content` selected
- add `Brief` if you want the tool to restate the request clearly
- add `Plan` if you want strategy ideas
- add `Evaluation` if you want scoring and risk notes

Then type your request in the large prompt box and click `Send`.

You can also press `Ctrl + Enter` on Windows or `Cmd + Enter` on Mac.

### Example prompt

Use plain language. You do not need special formatting.

Example:

> Write 3 LinkedIn opening lines for a webinar about AI reporting for B2B marketers. Keep the tone confident and practical. Avoid hype.

### When to use regular chat

Use `Chat` mode when you want help with:

- turning rough notes into clean copy
- summarizing a meeting
- rewriting a paragraph
- asking for campaign ideas
- getting feedback on existing text

`Chat` mode is simpler. `Marketing` mode is better when you want channel, audience, and objective to shape the answer.

## Model and Thinking Depth

At the top of each conversation, you can change:

- `Model`
- `Thinking Depth`

Simple guidance:

- leave `Model` on the default unless your team lead tells you otherwise
- use `Standard` for most tasks
- use `Deeper` or `Deep` when the work is more strategic or complex and you do not mind waiting longer

## Using a Knowledge Base

### What a Knowledge Base is

A Knowledge Base is a saved reference for the assistant. It can include:

- brand voice
- positioning
- approved terms
- words to avoid
- claims rules
- examples
- notes

Use it when you want the assistant to stay closer to your brand rules.

### Attach a Knowledge Base to a conversation

On the main page, choose:

- a `Knowledge Base`
- a `Knowledge Base Version`

If you do not want one, choose `No Knowledge Base`.

Once attached, the assistant will use that version in the current conversation.

### Create or update a Knowledge Base

Open `Knowledge Base Management`.

You will see:

- a list of existing Knowledge Bases on the left
- a form on the right for the selected version or a new version

Important fields:

- `Target key for new version`: the stable internal name, such as `brand_main`
- `Knowledge Base Name`: the friendly name people see
- `Brand Voice`: how the brand should sound
- `Positioning`: what the product is, who it is for, and why it matters
- `Glossary`: approved terms and preferred wording
- `Forbidden Words`: terms to avoid
- `Required Terms`: terms that should appear when relevant
- `Claims Policy`: what you can and cannot claim
- `Examples`: good examples to imitate
- `Notes`: anything else the team should remember

Good news: fields labeled `JSON or natural language` can be written in normal plain English. You do not need technical formatting for those.

Example:

- Brand Voice: `Clear, confident, practical, never exaggerated.`
- Positioning: `AI assistant for marketing teams that need faster drafting and clearer campaign execution.`
- Forbidden Words: `cheap, guaranteed, no-risk`

### When to create a new version

Create a new version when:

- the brand voice changed
- legal or claims rules changed
- product positioning changed
- you want a clean before-and-after record

Update the current version only for small fixes, such as correcting a typo or tightening wording.

## Uploading Documents

You can upload reference files into a conversation so the assistant can use them.

This is useful for:

- campaign briefs
- approved copy
- product notes
- messaging frameworks
- structured text exports

Current upload limits:

- maximum size: 3 MB per file
- supported types: `.txt`, `.md`, `.csv`, `.json`, `.log`, `.py`, `.html`, `.xml`, `.yaml`, `.yml`

Important:

- Word, PDF, and PowerPoint files are not supported directly in the current version
- if a file is rejected, convert it to plain text, Markdown, or CSV first

## Sharing Conversations

Every conversation has a visibility setting.

Options:

- `Private`: only you can access it
- `Task Group`: share with one approved task group
- `Company Group`: share with one approved company group

To share a conversation:

1. Open the conversation.
2. Choose the visibility.
3. If needed, choose the matching share group.
4. Click `Save Visibility`.

Notes:

- you must already be an approved member of the group
- a shared conversation can appear in other members' sidebars
- the app can show who shared it

Use `Private` for draft or sensitive work. Share only when the content is ready for team visibility.

## Exporting a Conversation

Click `Export Chat` to download the conversation as a Markdown text file.

This is useful for:

- handing off work
- saving a record
- moving copy into another document

## Groups

Open `Group Management` when you need to work with team access.

There are 2 group types:

- `Task Group`: for a specific campaign, workstream, or project team
- `Company Group`: for a broader shared team space

What most users need to know:

- you can request to join a group
- group admins approve requests
- you may also receive an invitation
- you must be approved before you can use that group for sharing

If you create a group, you become its first admin.

## Comparing Options

If you want to compare multiple copy options, you can still do that inside a normal conversation.

Simple workflow:

1. Create a `Marketing` conversation.
2. Ask for version A, version B, and version C in the same prompt.
3. Rename the conversation clearly, for example `Q2 Webinar Email Variants`.
4. Export or share the conversation when the team is ready to review it.

Example request:

> Write 3 homepage headline options for the same offer. Label them A, B, and C, and explain the strength of each.

## Recommended Team Habits

- Create one conversation per campaign or workstream.
- Rename conversations so they are easy to find later.
- Attach the correct Knowledge Base before generating important customer-facing copy.
- Keep draft work private until it is ready to share.
- Use task groups for campaign work and company groups for broader reusable work.
- Create a new Knowledge Base version when brand rules change in a meaningful way.
- Keep comparison work in one clearly named conversation so your team can review versions together.

## Common Problems and Fixes

### I cannot log in

- check that your username and password are correct
- if you had many failed attempts, wait a bit and try again
- if your account is disabled, contact an admin

### I cannot see a group in the sharing menu

- you probably are not an approved member yet
- ask the group admin to approve your request or invite you

### I cannot attach a Knowledge Base

- make sure you have access to that Knowledge Base version
- shared Knowledge Bases only appear if you are in the right approved group

### My file upload failed

- keep the file under 3 MB
- use a supported text-based format
- convert Word or PDF files to text, Markdown, or CSV first

### A teammate cannot see my conversation

- open the conversation
- set the right visibility
- choose the correct group
- click `Save Visibility`

### The answer is too generic

- switch to `Marketing` mode
- fill in channel, audience, objective, and extra requirements
- attach the right Knowledge Base
- upload a useful reference file
- be more specific in the prompt

## Best Starter Prompts

- `Write 5 subject lines for a webinar invite aimed at B2B marketers.`
- `Rewrite this landing page section so it sounds more confident and less technical.`
- `Turn these product notes into 3 LinkedIn post ideas.`
- `Create an email nurture draft for trial users who have not activated yet.`
- `Compare these two CTAs and explain which is stronger for conversion.`

## Final Reminder

You do not need to use every feature every time.

For most users, the simplest successful workflow is:

1. Create a `Marketing` conversation.
2. Fill in channel, audience, and objective.
3. Attach the right Knowledge Base if one exists.
4. Type a clear request.
5. Share or export the result when it is ready.
