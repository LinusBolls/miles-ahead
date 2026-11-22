// Deep link target: fuelback://rescue/<vehicleId> (push notifications, the widget) -> the map with that car's offer.
import { Redirect, useLocalSearchParams } from "expo-router";

export default function RescueLink() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <Redirect href={{ pathname: "/", params: { rescue: String(id ?? "") } }} />;
}
