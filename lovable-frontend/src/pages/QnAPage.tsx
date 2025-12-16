import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

const BACKEND_BASE =
  (import.meta.env.VITE_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');

interface QnAItem {
  category: string;
  question: string;
  answer: string;
  related_links: { title: string; url: string }[];
}

interface QnAData {
  items: QnAItem[];
  categories: string[];
  menus?: {
    name: string;
    slug: string;
    price_per_person: number;
    description: string;
    availability_window?: string;
    courses?: {
      starter?: string;
      main?: string;
      dessert?: string;
    };
    dietary?: string[];
  }[];
}

interface SnapshotContext {
  snapshotId: string | null;
  createdAt: string | null;
  title: string | null;
}

export default function QnAPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const snapshotId = searchParams.get('snapshot_id');
  const selectedCategory = searchParams.get('category');
  const [data, setData] = useState<QnAData>({ items: [], categories: [] });
  const [loading, setLoading] = useState(true);
  const [snapshotContext, setSnapshotContext] = useState<SnapshotContext>({
    snapshotId: null,
    createdAt: null,
    title: null,
  });

  const queryFilters = {
    month: searchParams.get('month'),
    vegetarian: searchParams.get('vegetarian'),
    vegan: searchParams.get('vegan'),
    courses: searchParams.get('courses'),
    wine_pairing: searchParams.get('wine_pairing'),
    date: searchParams.get('date'),
    capacity: searchParams.get('capacity'),
  };

  const formatAvailability = (value?: string) => {
    if (!value) return 'All year';
    const normalized = String(value);
    const parts = normalized.split('–').map(v => v.trim());
    const toAbbr = (label: string) => {
      if (!label || typeof label !== 'string') return label;
      const lower = label.toLowerCase();
      const map: Record<string, string> = {
        january: 'Jan', february: 'Feb', march: 'Mar', april: 'Apr', may: 'May', june: 'Jun',
        july: 'Jul', august: 'Aug', september: 'Sept', sept: 'Sept', october: 'Oct',
        november: 'Nov', december: 'Dec'
      };
      return map[lower] || label;
    };
    if (parts.length === 2) return `${toAbbr(parts[0])}–${toAbbr(parts[1])}`;
    return toAbbr(normalized);
  };

  const getFilterDescription = () => {
    const parts: string[] = [];

    if (queryFilters.month) {
      parts.push(`in ${queryFilters.month.charAt(0).toUpperCase() + queryFilters.month.slice(1)}`);
    }
    if (queryFilters.vegetarian === 'true') {
      parts.push('vegetarian');
    }
    if (queryFilters.vegan === 'true') {
      parts.push('vegan');
    }
    if (queryFilters.courses) {
      parts.push(`${queryFilters.courses}-course`);
    }
    if (queryFilters.wine_pairing === 'true') {
      parts.push('with wine pairing');
    }
    if (queryFilters.date) {
      parts.push(`on ${queryFilters.date}`);
    }
    if (queryFilters.capacity) {
      parts.push(`for ${queryFilters.capacity}+ people`);
    }

    return parts.length > 0 ? parts.join(', ') : null;
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
            title: snapshot.data?.title || null,
          });

          const snapshotData = snapshot.data || {};
          const transformedData: QnAData = {
            items: [],
            categories: ['Catering'],
            menus: snapshotData.menus || [],
          };

          setData(transformedData);
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
      if (selectedCategory) params.append('category', selectedCategory);
      if (queryFilters.month) params.append('month', queryFilters.month);
      if (queryFilters.vegetarian) params.append('vegetarian', queryFilters.vegetarian);
      if (queryFilters.vegan) params.append('vegan', queryFilters.vegan);
      if (queryFilters.courses) params.append('courses', queryFilters.courses);
      if (queryFilters.wine_pairing) params.append('wine_pairing', queryFilters.wine_pairing);
      if (queryFilters.date) params.append('date', queryFilters.date);
      if (queryFilters.capacity) params.append('capacity', queryFilters.capacity);

      const newUrl = `${BACKEND_BASE}/api/qna?${params.toString()}`;
      const oldUrl = `${BACKEND_BASE}/api/test-data/qna?${params.toString()}`;

      fetch(newUrl)
        .then(res => res.json())
        .then(newData => {
          if (newData.success && newData.handled) {
            const transformedData = {
              items: newData.items || [],
              categories: newData.categories || [],
              menus: newData.data?.menus || newData.data?.db_summary?.menus || newData.menus || []
            };
            setData(transformedData);
            setLoading(false);
          } else {
            return fetch(oldUrl).then(res => res.json());
          }
        })
        .then(oldData => {
          if (oldData) {
            setData(oldData);
            setLoading(false);
          }
        })
        .catch(err => {
          console.error('Failed to load Q&A:', err);
          fetch(oldUrl)
            .then(res => res.json())
            .then(oldData => {
              setData(oldData);
              setLoading(false);
            })
            .catch(() => setLoading(false));
        });
    }
  }, [snapshotId, selectedCategory, queryFilters.month, queryFilters.vegetarian, queryFilters.vegan,
      queryFilters.courses, queryFilters.wine_pairing, queryFilters.date, queryFilters.capacity]);

  const handleCategoryChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const cat = e.target.value;
    if (cat === 'all') {
       navigate('/info/qna');
    } else {
       navigate(`/info/qna?category=${encodeURIComponent(cat)}`);
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading information...</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-8 max-w-5xl">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <h1 className="text-3xl font-bold text-gray-900">Frequently Asked Questions</h1>

        <div className="w-full md:w-64">
            <label htmlFor="category-select" className="sr-only">Select Category</label>
            <select
                id="category-select"
                className="w-full p-2 border border-gray-300 rounded-lg shadow-sm bg-white text-gray-700 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                value={selectedCategory || 'all'}
                onChange={handleCategoryChange}
            >
                <option value="all">All Questions</option>
                {data.categories.map(cat => (
                    <option key={cat} value={cat}>{cat}</option>
                ))}
            </select>
        </div>
      </div>

      <main>
        {selectedCategory && (
          <div className="mb-6 text-gray-600">
            Showing questions about: <span className="font-semibold">{selectedCategory}</span>
          </div>
        )}

        {getFilterDescription() && (
          <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="text-sm font-semibold text-blue-900 mb-1">Active Filters:</div>
            <div className="text-blue-800">{getFilterDescription()}</div>
          </div>
        )}

        <div className="space-y-6">
          {data.items.map((item, idx) => (
            <div
              key={idx}
              className="bg-white border rounded-lg p-6 shadow-sm hover:shadow-md transition-shadow"
            >
              <div className="text-sm text-gray-500 mb-2">
                {item.category}
              </div>
              <h3 className="text-xl font-semibold mb-3 text-gray-900">
                {item.question}
              </h3>
              <div className="text-gray-700 leading-relaxed">
                {item.answer}
              </div>

              {item.related_links.length > 0 && (
                <div className="mt-4 pt-4 border-t">
                  <h4 className="text-sm font-semibold text-gray-600 mb-2">
                    Related Information
                  </h4>
                  <ul className="space-y-1">
                    {item.related_links.map((link, linkIdx) => (
                      <li key={linkIdx}>
                        <a
                          href={link.url}
                          className="text-blue-600 hover:underline text-sm"
                        >
                          {link.title} →
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      </main>

      <div className="mt-12 text-center text-gray-600">
        <p>Still have questions? Return to your booking conversation for personalized assistance.</p>
      </div>

      {data.menus && data.menus.length > 0 && (
        <div className="mt-12 max-w-5xl mx-auto">
          <h2 className="text-2xl font-semibold mb-4">Catering menus (full details)</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {data.menus.map(menu => (
              <a
                key={menu.slug}
                href={`/info/catering/${menu.slug}`}
                className="border rounded-lg p-4 bg-white hover:shadow-md transition-shadow"
              >
                <div className="flex justify-between items-start mb-2">
                  <span className="font-semibold text-gray-900">{menu.name}</span>
                  <span className="text-blue-600 font-medium">{menu.price_per_person} pp</span>
                </div>
                <p className="text-gray-700 text-sm mb-2">{menu.description}</p>
                {menu.availability_window && (
                  <div className="text-xs text-gray-600 mb-2">
                    Availability: {formatAvailability(menu.availability_window)}
                  </div>
                )}
                {menu.courses && (
                  <ul className="text-sm text-gray-700 space-y-1">
                    {menu.courses.starter && <li><strong>Starter:</strong> {menu.courses.starter}</li>}
                    {menu.courses.main && <li><strong>Main:</strong> {menu.courses.main}</li>}
                    {menu.courses.dessert && <li><strong>Dessert:</strong> {menu.courses.dessert}</li>}
                  </ul>
                )}
                {menu.dietary && menu.dietary.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {menu.dietary.map(tag => (
                      <span key={tag} className="px-2 py-1 bg-green-100 text-green-700 rounded text-xs">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
