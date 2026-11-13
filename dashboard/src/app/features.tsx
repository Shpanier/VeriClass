import { createContext, useContext } from "react";

export interface Features {
  /** Show the screens that only matter with the IDE plugin: exam monitoring,
   *  the terminal log, submissions and grades, verifying an exported log.
   *  The server decides (PLUGIN_UI, or whether a plugin was ever used here). */
  plugin: boolean;
}

const Ctx = createContext<Features>({ plugin: false });
export const FeaturesProvider = Ctx.Provider;
export const useFeatures = () => useContext(Ctx);
