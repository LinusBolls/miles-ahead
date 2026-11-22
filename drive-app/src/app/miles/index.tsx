import { useEffect, useState } from "react";
import { useLocalSearchParams } from "expo-router";
import { MilesHomeScreen } from "@/miles/MilesHomeScreen";

export default function MilesHome() {
  const { car } = useLocalSearchParams<{ car?: string }>();
  const [sel, setSel] = useState<number | null>(car ? Number(car) : null);
  useEffect(() => {
    if (car) setSel(Number(car));
  }, [car]);
  return <MilesHomeScreen selectedId={sel} onSelectVehicle={setSel} />;
}
