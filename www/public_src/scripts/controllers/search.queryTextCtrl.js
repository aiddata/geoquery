angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $stateParams) {
  $scope.filters = {};
  $scope.dataset = {};
  $scope.searchData = {};
  $scope.geography = $stateParams.boundary;

  $rootScope.$on('filters:update', function(e, data) {
    console.log('FILTER', data);
    $scope.searchData = data;
  });

  $rootScope.$on('filters:updated', function(e, data) {
    console.log('FILTERS', data);

    $scope.queryStructure = [
      { value: [ $scope.dataset.title ], pre: 'Extract data from ', optional: false },
      { value: [ $scope.geography ], pre: 'within ', optional: false },
      { value: $scope.searchData.donors, pre: 'given by ', optional: true, key: 'donors' },
      { value: $scope.searchData.ad_sector_names, pre: 'to promote ', optional: true, key: 'ad_sector_names' }
    ];

    $scope.filters = data;
  });

  $rootScope.$on('dataset:selected', function(e, data) {
    console.log('DATASET', data);
    $scope.dataset = data;
  });

  $scope.removeFilter = function (filter, option) {
    console.log(filter, option);
  };
});
