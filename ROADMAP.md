# Twitter Bookmarks — Roadmap

## Phase 1: Core Pipeline (Current)
- [x] Get bookmark_merger.py working with existing Chrome extension exports
- [ ] Build birdmarks bridge (fetch command) to pull bookmarks via API
- [ ] Match output format to Chrome extension exports
- [ ] Fetch all unsynced bookmarks, generate HTML site
- [ ] Push → Nikolaj publishes manually

## Phase 2: Automation
- [ ] Cron job on server: refresh new bookmarks hourly
- [ ] Push → Nikolaj publishes

## Phase 3: Social & AI Features
- [ ] Invite users to view bookmarks (access control)
- [ ] Discussion/conversation rooms per bookmark
  - Start from bookmark → open conversation
  - Find in "conversations" → contribute
  - Sparse by design (not every bookmark gets a room)
  - Own interface: a) start from bookmark, b) browse conversations
- [ ] Local AI investigation per bookmark (like Grok on x.com)
  - Query AI about tweet content, linked articles, context
  - Users can see AI investigations and contribute
  - Think: conversation room with AI + humans

## Phase 4: Ordet Integration
- [ ] Ordet monitors bookmarks for patterns and actionable items
- [ ] Discuss bookmarks together (Nikolaj + Ordet)
- [ ] Some bookmarks → try out / act on
- [ ] Some stay dormant
- [ ] Pattern detection: many bookmarks of same type → suggest new project/room
- [ ] Integration with Matrix rooms for project discussions
