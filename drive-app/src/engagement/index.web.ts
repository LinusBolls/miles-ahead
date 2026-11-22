// Web twin of src/engagement/index.ts: Live Activities, widgets and native push don't exist on the web. All no-ops.
type DateLike = number | string | Date;

export async function startRescueActivity(_args: {
  carModel: string;
  plate: string;
  rewardEur: number;
  walkMin: number;
  destinationName: string;
  expiresAt?: DateLike;
}): Promise<void> {}

export async function updateRescueActivity(_args: {
  stage: "walking" | "driving" | "done";
  minutesLeft?: number;
}): Promise<void> {}

export async function endRescueActivity(): Promise<void> {}

export async function setWidgetData(_args: {
  nearbyCount: number;
  bestRewardEur: number;
  bestWalkMin: number;
  updatedAt: DateLike;
  bestVehicleId?: string | number;
}): Promise<void> {}

export async function registerForPush(): Promise<string | null> {
  return null;
}

export function getPushToken(): string | null {
  return null;
}

export async function showPushToken(): Promise<void> {}

export function useRescueEngagement(): void {}
