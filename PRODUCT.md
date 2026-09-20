# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People who encounter an X post and want to understand how its subject spread through the surrounding public conversation. Hackathon judges are a secondary audience seeing the product through the recorded Dario example.

## Product Purpose

Sequitor lets a user enter an X post or topic, retrieves related public posts, and makes their observed replies, quotes, chronology, and semantic proximity explorable. Success means a user can move from a single post to an intelligible conversation without mistaking retrieval or similarity for proof of influence or truth.

## Positioning

Sequitor's distinguishing experience is a conversation that visibly assembles from a starting point while its retrieved posts appear in both an interactive spatial view and a readable lineage.

## Operating Context

The current frontend is a React/TypeScript/Vite web app with Three.js. A Railway backend streams investigation events through SSE. The Dario Amodei recorded example is the required desktop demo.

## Capabilities and Constraints

- The first implementation target is desktop web only.
- The user enters a post link or a topic.
- Backend events resolve a seed, plan searches, measure activity, and upsert posts progressively.
- Conversation Space positions posts from a frozen recorded projection or a live/lexical fallback.
- Reply and quote links are observed relationships; semantic similarity is not lineage.
- The interface must avoid provider/model names, implementation notes, and technical footnotes in the main flow.

## Brand Commitments

The product is named Sequitor. The user specified a simple, sleek dark experience with a single cinematic search-to-conversation transition. The viewer is the main attraction; information should be minimal and subordinate to it.

## Evidence on Hand

- Recorded Dario example: `demo/recordings/sequitor-live.json`.
- Conversation-space projection: `demo/recordings/conversation-space.json`.
- Existing public-post avatars, text, timestamps, and observed links in the recording files.

## Product Principles

- Show the conversation arriving rather than presenting a static dashboard.
- Keep the starting point, actual posts, and observed links legible.
- Let users take control immediately when they interact.
- State only what the captured evidence supports.
- Keep technical machinery out of the primary experience.
