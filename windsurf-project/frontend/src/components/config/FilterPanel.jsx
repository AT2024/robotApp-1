// // src/components/config/FilterPanel.jsx
// import React from 'react';
// import { Filter } from 'lucide-react';

// const FilterButton = ({ label, isSelected, onClick }) => (
//   <button
//     onClick={onClick}
//     className={`px-3 py-2 rounded-full text-sm font-medium transition-colors ${
//       isSelected
//         ? 'bg-blue-100 text-blue-700 hover:bg-blue-200'
//         : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
//     }`}
//   >
//     {label}
//   </button>
// );

// const FilterPanel = ({ sections, selectedSections, onChange }) => {
//   const handleSectionToggle = (section) => {
//     const newSelected = selectedSections.includes(section)
//       ? selectedSections.filter(s => s !== section)
//       : [...selectedSections, section];
//     onChange(newSelected);
//   };

//   const handleShowAll = () => {
//     onChange(sections);
//   };

//   return (
//     <div className="mb-6 p-4 bg-white rounded-lg shadow-sm border border-gray-200">
//       <div className="flex items-center gap-2 mb-4">
//         <Filter className="w-5 h-5 text-gray-600" />
//         <h3 className="text-lg font-semibold text-gray-800">Filter Sections</h3>
//       </div>
//       <div className="flex flex-wrap gap-2">
//         {sections.map((section) => (
//           <FilterButton
//             key={section}
//             label={section}
//             isSelected={selectedSections.includes(section)}
//             onClick={() => handleSectionToggle(section)}
//           />
//         ))}
//         <FilterButton
//           label="Show All"
//           isSelected={selectedSections.length === sections.length}
//           onClick={handleShowAll}
//         />
//       </div>
//     </div>
//   );
// };

// export default FilterPanel;