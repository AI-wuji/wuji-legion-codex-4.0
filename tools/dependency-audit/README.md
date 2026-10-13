# P0 依赖解析审计

仅用于Cargo生成精确依赖闭包、读取上游许可元数据与来源hash。空lib目标供Cargo解析manifest，不包含任何军团运行实现，不是Rust选型原型。

只运行generate-lockfile、fetch或metadata，不运行build/test、不调用模型或用户工具。这里的锁与缓存不是军团根Cargo.lock，也不是G0/G1放行；正式核心须在G1通过后全新实现并按实际依赖重新锁定。

工具链与Cargo缓存仅位于本项目.dev内，使用子进程环境，不修改全局PATH、用户cargo目录或当前Codex。原项目、provider、插件、音频与用户文件不动。
