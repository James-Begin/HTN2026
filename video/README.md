# Sequitor animated demo

The portfolio video is rendered frame by frame from React components and saved Dario investigation data. It does **not** use the screen recording as a video layer. The old recording and the app UI informed the composition; the animated text, cards, camera, nodes, links, sidebar, and timeline are generated from code.

## Storyboard (1920 × 1080, 30 fps)

| Time | Scene | Motion and purpose |
| --- | --- | --- |
| 0:00–0:03.5 | Logo | A cyan trace resolves into the Sequitor wordmark. Hold long enough to read the name. |
| 0:03.5–0:11.5 | Landing | The search field types Dario's actual post opening. A click sends the interface through a cyan genie-shaped collapse. |
| 0:11.5–0:20.5 | Search | Recognizable post cards float in a deep field. They start slow enough to read, then accelerate past the viewer into black. |
| 0:20.5–0:42 | Conversation | The reference node appears first. Actual captured posts and observed reply/quote links accumulate slowly, then faster, as the camera pulls back and the activity chart and post list reveal the full UI. |

The visual rhythm uses the reference ideas of focused product shots, deliberate camera movement, and a UI payoff, rather than recording a cursor for 40 seconds. Source examples: [X product-demo edit](https://x.com/DerekFeehrer/status/2028887848901067042), [Remotion prompt showcase](https://www.remotion.dev/prompts), and [Remotion Recorder's scene guidance](https://www.remotion.dev/docs/recorder).

## Rebuild

```bash
python3 video/build_data.py
cd video
npm ci
npm run render
npm run poster
```

The generator reads `demo/recordings/sequitor-live.json`, `demo/recordings/dario-humor.json`, and `demo/recordings/conversation-space.json`. It writes `src/data.json` with selected public posts, their saved semantic coordinates, and observed edges. The graph uses publication-order spacing (as the app's flow-time view does) and rotates the saved semantic plane a quarter turn without changing distances. The rendered output is `docs/assets/sequitor-demo.mp4`; the poster is `docs/assets/sequitor-poster.jpg`. To preview scene timing interactively, run `npm run studio`.

The clip is intentionally silent for autoplay on portfolio and social pages. The animated search is a depiction of the recorded example, not a new live X query.
