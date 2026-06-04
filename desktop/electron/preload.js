import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("anews", {
  platform: process.platform,
});
