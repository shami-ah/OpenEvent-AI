import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

const BACKEND_BASE =
  (import.meta.env.VITE_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');

interface Room {
  name: string;
  capacity: number;
  features: string[];
  status: 'Available' | 'Option' | 'Unavailable';
  price: number;
  description: string;
  equipment: string[];
  layout_options: string[];
  menus: {
    name: string;
    slug: string;
    price_per_person: number;
    summary: string;
    dietary_options: string[];
  }[];
}

interface SnapshotContext {
  snapshotId: string | null;
  createdAt: string | null;
  selectedRoom: string | null;
  displayDate: string | null;
}

export default function RoomsPage() {
  const [searchParams] = useSearchParams();
  const snapshotId = searchParams.get('snapshot_id');
  const date = searchParams.get('date');
  const capacity = searchParams.get('capacity');
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [snapshotContext, setSnapshotContext] = useState<SnapshotContext>({
    snapshotId: null,
    createdAt: null,
    selectedRoom: null,
    displayDate: null,
  });

  const formatDate = (value: string | null) => {
    if (!value) return null;
    const dateObj = new Date(value);
    if (Number.isNaN(dateObj.getTime())) return value;
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec'];
    return `${dateObj.getDate()} ${monthNames[dateObj.getMonth()]} ${dateObj.getFullYear()}`;
  };

  useEffect(() => {
    if (snapshotId) {
      fetch(`${BACKEND_BASE}/api/snapshots/${snapshotId}`)
        .then(res => res.json())
        .then(snapshot => {
          if (snapshot.error) {
            console.error('Snapshot not found:', snapshot.error);
            fetchByParams();
            return;
          }

          setSnapshotContext({
            snapshotId: snapshot.snapshot_id,
            createdAt: snapshot.created_at,
            selectedRoom: snapshot.data?.selected_room || null,
            displayDate: snapshot.data?.display_date || null,
          });

          const snapshotData = snapshot.data || {};
          const tableRows = snapshotData.table_rows || [];

          if (tableRows.length > 0) {
            const roomsFromSnapshot = tableRows.map((row: Record<string, unknown>) => ({
              name: row.name || row.room || 'Unknown',
              capacity: row.capacity || 0,
              features: row.features || [],
              status: row.status || 'Available',
              price: row.price || 0,
              description: row.description || '',
              equipment: row.equipment || [],
              layout_options: row.layout_options || [],
              menus: row.menus || [],
            }));
            setRooms(roomsFromSnapshot);
          } else {
            const verbalizerRooms = snapshotData.rooms || [];
            const roomsFromVerbalizer = verbalizerRooms.map((room: Record<string, unknown>) => ({
              name: room.name || room.id || 'Unknown',
              capacity: room.capacity || 0,
              features: Object.entries((room.badges as Record<string, unknown>) || {})
                .filter(([, v]) => v)
                .map(([k, v]) => `${k}: ${v}`),
              status: 'Available' as const,
              price: 0,
              description: (room.hint as string) || '',
              equipment: ((room.requirements as Record<string, unknown>)?.matched as string[]) || [],
              layout_options: (room.alternatives as string[]) || [],
              menus: [],
            }));
            setRooms(roomsFromVerbalizer);
          }
          setLoading(false);
        })
        .catch(err => {
          console.error('Failed to load snapshot:', err);
          fetchByParams();
        });
    } else {
      fetchByParams();
    }

    function fetchByParams() {
      const params = new URLSearchParams();
      if (date) params.append('date', date);
      if (capacity) params.append('capacity', capacity);

      fetch(`${BACKEND_BASE}/api/test-data/rooms?${params}`)
        .then(res => res.json())
        .then(data => {
          const withMenus = (data as Room[]).map(room => ({
            ...room,
            menus: room.menus || [],
          }));
          setRooms(withMenus);
          setLoading(false);
        })
        .catch(err => {
          console.error('Failed to load rooms:', err);
          setLoading(false);
        });
    }
  }, [snapshotId, date, capacity]);

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading room information...</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-8 max-w-7xl">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-4">Room Availability at The Atelier</h1>

        {/* Context display */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          {snapshotContext.snapshotId && (
            <div className="mb-2 text-sm text-blue-600">
              <span className="font-semibold">Viewing saved snapshot</span>
              {snapshotContext.createdAt && (
                <span className="ml-2 text-gray-500">
                  (saved {new Date(snapshotContext.createdAt).toLocaleString()})
                </span>
              )}
            </div>
          )}
          {(snapshotContext.displayDate || date) && (
            <div className="text-gray-700">
              <span className="font-semibold">Event Date:</span> {snapshotContext.displayDate || formatDate(date)}
            </div>
          )}
          {capacity && (
            <div className="text-gray-700">
              <span className="font-semibold">Required Capacity:</span> {capacity} participants
            </div>
          )}
          {snapshotContext.selectedRoom && (
            <div className="text-gray-700">
              <span className="font-semibold">Recommended:</span> {snapshotContext.selectedRoom}
            </div>
          )}
          {!date && !capacity && !snapshotContext.snapshotId && (
            <div className="text-gray-700">Showing all available rooms</div>
          )}
        </div>
      </div>

      {/* Quick comparison table */}
      <div className="mb-12">
        <h2 className="text-2xl font-semibold mb-4">Quick Comparison</h2>
        <div className="overflow-x-auto shadow-lg rounded-lg">
          <table className="min-w-full bg-white">
            <thead className="bg-gray-100 border-b">
              <tr>
                <th className="px-6 py-4 text-left font-semibold">Room</th>
                <th className="px-6 py-4 text-center font-semibold">Capacity</th>
                <th className="px-6 py-4 text-center font-semibold">Status</th>
                <th className="px-6 py-4 text-left font-semibold">Key Features</th>
                <th className="px-6 py-4 text-left font-semibold">Layouts</th>
                <th className="px-6 py-4 text-right font-semibold">Price/Day</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((room, idx) => (
                <tr key={idx} className="border-b hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 font-medium text-lg">{room.name}</td>
                  <td className="px-6 py-4 text-center">{room.capacity}</td>
                  <td className="px-6 py-4 text-center">
                    <span className={`inline-flex px-3 py-1 rounded-full text-sm font-medium ${
                      room.status === 'Available'
                        ? 'bg-green-100 text-green-800'
                        : room.status === 'Option'
                        ? 'bg-yellow-100 text-yellow-800'
                        : 'bg-red-100 text-red-800'
                    }`}>
                      {room.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm">
                    {room.features.slice(0, 3).join(' - ')}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    {room.layout_options.slice(0, 2).join(', ')}
                    {room.layout_options.length > 2 && ' ...'}
                  </td>
                  <td className="px-6 py-4 text-right font-semibold">
                    CHF {room.price.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detailed room cards */}
      <div>
        <h2 className="text-2xl font-semibold mb-6">Detailed Room Information</h2>
        <div className="space-y-6">
          {rooms.map((room, idx) => (
            <div
              key={idx}
              className="border rounded-lg shadow-md hover:shadow-lg transition-shadow bg-white"
            >
              {/* Room header */}
              <div className="bg-gray-50 px-6 py-4 border-b">
                <div className="flex justify-between items-center">
                  <h3 className="text-xl font-bold">{room.name}</h3>
                  <div className="text-lg font-semibold text-gray-700">
                    CHF {room.price.toLocaleString()} per day
                  </div>
                </div>
              </div>

              {/* Room content */}
              <div className="p-6">
                <p className="text-gray-700 mb-6 leading-relaxed">
                  {room.description}
                </p>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {/* Features */}
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-3">Features</h4>
                    <ul className="space-y-2">
                      {room.features.map((feature, fIdx) => (
                        <li key={fIdx} className="flex items-start">
                          <span className="text-green-500 mr-2">&#10003;</span>
                          <span className="text-gray-700">{feature}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Equipment */}
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-3">Equipment</h4>
                    <ul className="space-y-2">
                      {room.equipment.map((item, eIdx) => (
                        <li key={eIdx} className="flex items-start">
                          <span className="text-blue-500 mr-2">&#8226;</span>
                          <span className="text-gray-700">{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Layout Options */}
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-3">Layout Options</h4>
                    <div className="space-y-2">
                      {room.layout_options.map((layout, lIdx) => (
                        <div
                          key={lIdx}
                          className="bg-gray-100 px-3 py-2 rounded text-gray-700"
                        >
                          {layout}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Catering menus available for this room */}
                {room.menus.length > 0 && (
                  <div className="mt-8">
                    <h4 className="font-semibold text-gray-900 mb-3">Catering menus for this room</h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {room.menus.map(menu => (
                        <a
                          key={menu.slug}
                          href={`/info/catering/${menu.slug}?room=${encodeURIComponent(room.name)}${date ? `&date=${encodeURIComponent(date)}` : ''}`}
                          className="border rounded-lg p-4 hover:shadow-md transition-shadow"
                        >
                          <div className="flex justify-between items-start mb-2">
                            <span className="font-semibold text-gray-900">{menu.name}</span>
                            <span className="text-blue-600 font-medium">CHF {menu.price_per_person} pp</span>
                          </div>
                          <p className="text-gray-700 text-sm mb-2">{menu.summary}</p>
                          <div className="flex flex-wrap gap-2">
                            {menu.dietary_options.map(tag => (
                              <span key={tag} className="px-2 py-1 bg-green-100 text-green-700 rounded text-xs">
                                {tag}
                              </span>
                            ))}
                          </div>
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="mt-12 text-center text-gray-600">
        <p>Return to your booking conversation to select a room</p>
      </div>
    </div>
  );
}
