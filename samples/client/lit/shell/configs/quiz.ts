/*
 Copyright 2025 Google LLC

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      https://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
 */

import { AppConfig } from "./types.js";

export const config: AppConfig = {
  key: "quiz",
  title: "クイズジェネレーター",
  background: `radial-gradient(
    at 0% 0%,
    light-dark(rgba(168, 85, 247, 0.3), rgba(139, 92, 246, 0.2)) 0px,
    transparent 50%
  ),
  radial-gradient(
    at 100% 0%,
    light-dark(rgba(236, 72, 153, 0.3), rgba(219, 39, 119, 0.2)) 0px,
    transparent 50%
  ),
  radial-gradient(
    at 100% 100%,
    light-dark(rgba(251, 146, 60, 0.3), rgba(249, 115, 22, 0.2)) 0px,
    transparent 50%
  ),
  radial-gradient(
    at 0% 100%,
    light-dark(rgba(34, 211, 238, 0.3), rgba(6, 182, 212, 0.2)) 0px,
    transparent 50%
  ),
  linear-gradient(
    135deg,
    light-dark(#faf5ff, #1e1b4b) 0%,
    light-dark(#fdf2f8, #312e81) 100%
  )`,
  placeholder: "日本の歴史について5問出題して",
  loadingText: [
    "クイズを生成しています...",
    "問題を考え中...",
    "選択肢を準備しています...",
    "もう少しお待ちください...",
  ],
  serverUrl: "http://localhost:10004",
};
