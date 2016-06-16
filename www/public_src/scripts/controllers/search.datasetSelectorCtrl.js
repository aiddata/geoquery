angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $stateParams, $q, ajaxFactory) {
  $scope.datasets = [];
  $scope.fields = {
    options: ['date_added', 'date_updated', 'title', 'publishers', 'version'],
    selected: 'title',
    descending: false
  };

  $scope.dataTypes = [
    { text: 'AidData', value: 'release' },
    { text: 'External', value: 'raster' },
    { text: 'All', value: '' }
  ];

  $scope.dataFilters = { type: '', title: '' };

  ajaxFactory.datasets($stateParams.geomId)
    .then(function(results) {
      $scope.datasets = results.data;
      console.log(results.data);
      $scope.selectDataset();
    });

  $scope.selectDataset = function() {
    $rootScope.$broadcast('dataset:selected', { dataset: "drc-aims_geocodedresearchrelease_level1_v1_3" });
  };
});
